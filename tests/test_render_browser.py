"""Real Chromium checks for the browser's request guard; skipped without the render extra
(run them where `playwright install chromium` was done)."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("playwright")

from ant_peer_review.sources.crawler import Crawler  # noqa: E402
from ant_peer_review.sources.htmlmd import html_to_markdown  # noqa: E402
from ant_peer_review.sources.render import PlaywrightRenderer  # noqa: E402


class H(BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        H.seen.append(self.path)
        port = self.server.server_address[1]
        if self.path == "/story":
            # The WebSocket opens first and /slow keeps the network busy. Observed
            # 2026-10-22 (Chromium 156): from a document served by route.fulfill the socket
            # never connects even without route_web_socket, so this assertion cannot catch
            # that guard's removal; the guard stays as the documented control.
            body = (f"<html><body><script>new WebSocket('ws://127.0.0.1:{port}/ws')</script>"
                    f"<article id=a></article><img src='http://localhost:{port}/r'>"
                    f"<img src='http://localhost:{port}/r2'><img src='http://localhost:{port}/slow'>"
                    f"<script>window.open('http://127.0.0.1:{port}/popup');"
                    "for(let i=0;i<6;i++)document.getElementById('a').insertAdjacentHTML("
                    "'beforeend','<p>Rendered paragraph '+i+' of a JavaScript article.</p>')"
                    "</script></body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        elif self.path == "/slow":
            import time
            time.sleep(1.5)
            body = b""
            self.send_response(204)
        elif self.path in ("/r", "/r2"):
            body = b""
            self.send_response(302)
            dest = "127.0.0.1" if self.path == "/r" else "localhost"
            self.send_header("Location", f"http://{dest}:{port}/{'secret' if dest[0] == '1' else 'ok'}")
        else:
            body = b"x"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


# @S-source-acquisition-041
def test_real_browser_never_reaches_internal_addresses():
    H.seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    c = Crawler(resolver=lambda h, p: ["127.0.0.1"], _allow_hosts_for_tests=frozenset({"localhost"}))
    try:
        html, final = PlaywrightRenderer().render(
            f"http://localhost:{port}/story", allow=c.request_allowed,
            allow_navigation=c.request_allowed, user_agent="ant-peer-review/test",
            max_bytes=10_000_000, timeout=20)
    finally:
        srv.shutdown()
    assert html_to_markdown(html).markdown.count("Rendered paragraph") == 6
    assert not {"/secret", "/popup", "/ws"} & set(H.seen), H.seen
    assert "/ok" in H.seen and final == f"http://localhost:{port}/story"

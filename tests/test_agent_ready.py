import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ant_peer_review.analysis import identity
from ant_peer_review.i18n import T
from ant_peer_review.jsonio import read_json
from ant_peer_review.sources.crawler import Crawler
from test_fallback import FULL, THIN, URL, FakeCrawler, FakeRenderer, run_for, text_of

REPO = "https://github.com/storytold/craft-anything"
RAW = "https://raw.githubusercontent.com/storytold/craft-anything/HEAD/README.md"
README = '<p align="center"><img src="a.png"></p>\n\n<h1>Craft Anything</h1>\n\n' + "A README paragraph that explains the project in words. " * 8


def test_html_blocks_in_markdown_become_text():
    from ant_peer_review.sources.agentready import html_blocks_to_text
    md = ('<p align="center"><img src="logo.png"></p>\n\n<h1 align="center">Craft Anything</h1>\n\n'
          '<p align="center"><b>See how any website works</b> · <a href="x">Docs</a></p>\n\n'
          "Plain paragraph.\n\n```html\n<p>kept in code</p>\n```\n")
    out = html_blocks_to_text(md)
    assert "<p" not in out.split("```")[0] and "<img" not in out
    assert "# Craft Anything" in out and "See how any website works" in out
    assert "<p>kept in code</p>" in out and "Plain paragraph." in out


# @S-source-acquisition-045
def test_github_repo_read_from_raw_readme(tmp_path):
    c = FakeCrawler(pages={RAW: ("text/plain", README)})
    run, item = run_for(tmp_path, c, url=REPO)
    assert c.calls == [RAW] and item["status"] == "ok" and item["via"] == "github_readme"
    doc = item["docs"][0]
    assert doc["origin"] == REPO and doc["title"] == "Craft Anything"
    assert "A README paragraph" in text_of(run)
    assert T("en")("via.github_readme") == "GitHub README (raw)"

    blob = "https://github.com/o/r/blob/main/docs/guide.md"
    raw = "https://raw.githubusercontent.com/o/r/main/docs/guide.md"
    c = FakeCrawler(pages={raw: ("text/plain", README)})
    run_for(tmp_path / "b", c, url=blob)
    assert c.calls == [raw]

    page = "<html><head><title>repo</title></head><body><article class='markdown-body'>" + \
        "".join(f"<p>Rendered README paragraph {i} with enough words in it.</p>" for i in range(8)) + \
        "</article></body></html>"
    c = FakeCrawler(pages={REPO: ("text/html", page)})          # raw missing: the page as before
    run, item = run_for(tmp_path / "c", c, url=REPO)
    assert c.calls == [RAW, REPO] and item["via"] == "direct"
    assert "Rendered README paragraph" in text_of(run)


class Echo(BaseHTTPRequestHandler):
    seen = []
    ctype = "text/markdown"

    def do_GET(self):
        if self.path == "/robots.txt":
            self.send_response(404)
            self.end_headers()
            return
        Echo.seen.append(self.headers.get("Accept"))
        body = b"# Title\n\nPlain markdown body." if Echo.ctype == "text/markdown" else b"{}"
        self.send_response(200)
        self.send_header("Content-Type", Echo.ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


# @S-source-acquisition-046
def test_markdown_asked_first():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = Crawler(resolver=lambda h, p: ["127.0.0.1"], min_interval=0,
                    _allow_hosts_for_tests=frozenset({"pub.example"}))
        base = f"http://pub.example:{srv.server_address[1]}"
        res = c.fetch(base + "/a")
        assert Echo.seen[-1].startswith("text/markdown, text/html;q=0.9, ")
        assert res.content_type == "text/markdown" and res.body.startswith(b"# Title")
        Echo.ctype = "application/json"
        c.fetch(base + "/api", types=("application/json",))
        assert Echo.seen[-1] == "application/json"
    finally:
        Echo.ctype = "text/markdown"
        srv.shutdown()


LD = {"@context": "https://schema.org", "@graph": [
    {"@type": "WebSite", "name": "Site"},
    {"@type": "NewsArticle", "headline": "LD title", "author": [{"@type": "Person", "name": "Ada"}],
     "datePublished": "2026-03-04T05:06:07Z", "publisher": {"@type": "Organization", "name": "LD News"},
     "articleBody": " ".join(["The full article body sentence from structured data."] * 10)}]}


def page(ld: str, body: str = "") -> str:
    return (f"<html><head><title>Meta title</title><meta name='author' content='Meta Author'>"
            f"<meta property='og:site_name' content='Meta News'>"
            f"<meta property='article:published_time' content='2025-01-01'>"
            f"<script type='application/ld+json'>{ld}</script></head><body>{body}</body></html>")


# @S-source-acquisition-047
def test_jsonld_identity_first():
    got = identity({"kind": "url", "value": URL}, page(json.dumps(LD)), "")
    assert (got["title"], got["author"], got["date"], got["organization"]) == \
        ("LD title", "Ada", "2026-03-04", "LD News")
    got = identity({"kind": "url", "value": URL}, page("{broken"), "")
    assert (got["title"], got["author"], got["date"], got["organization"]) == \
        ("Meta title", "Meta Author", "2025-01-01", "Meta News")


# @S-source-acquisition-048
def test_jsonld_body_only_for_thin_pages(tmp_path):
    thin = page(json.dumps(LD), THIN.decode().split("<body>")[1].split("</body>")[0])
    c = FakeCrawler(pages={URL: ("text/html", thin)})
    r = FakeRenderer()
    run, item = run_for(tmp_path, c, r)
    assert r.calls == [] and item["via"] == "jsonld" and item["fell_back_from"] == "thin_page"
    assert "full article body sentence from structured data" in text_of(run)
    assert T("en")("via.jsonld") == "JSON-LD articleBody"

    full_html = FULL.replace("</head>", f"<script type='application/ld+json'>{json.dumps(LD)}</script></head>")
    c = FakeCrawler(pages={URL: ("text/html", full_html)})
    run, item = run_for(tmp_path / "b", c, FakeRenderer())
    assert item["via"] == "direct" and "Paragraph 3 of the full article" in text_of(run)
    assert "structured data" not in text_of(run)
    assert read_json(run.path("01-sources/manifest.json"))["items"][0]["via"] == "direct"

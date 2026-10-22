"""D-PR-15: fetch fallback order -- retries, browser, AMP, archive, paste."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlsplit

import pytest

from ant_peer_review.jsonio import read_json, write_json
from ant_peer_review.sources.acquire import ARCHIVE_API, run_sources
from ant_peer_review.sources.crawler import Crawler, FetchError, FetchResult
from ant_peer_review.workspace import create_run

URL = "https://news.example/story"
THIN = (b"<html><body><div id='app'></div><p>Loading the story, the application is starting up "
        b"in your window right now.</p></body></html>")
EMPTY = b"<html><body><div id='app'></div></body></html>"
CHALLENGE = (b"<html><head><title>Just a moment...</title></head><body><div id='cf-chl-widget'>"
             b"</div><p>Checking your browser.</p></body></html>")
FULL = ("<html><head><title>Story</title></head><body><article>"
        + "".join(f"<p>Paragraph {i} of the full article text, long enough to read.</p>"
                  for i in range(8)) + "</article></body></html>")
TS = "20260102030405"
SNAP = f"https://web.archive.org/web/{TS}id_/{URL}"


class FakeCrawler:
    max_bytes, timeout = 10_000_000, 5.0

    def __init__(self, pages=None, fail=None, profiles=None):
        self.pages, self.fail, self.profiles = pages or {}, fail or {}, profiles or {}
        self.calls = []

    def profile_for(self, url):
        return self.profiles.get(urlsplit(url).hostname, {})

    def request_allowed(self, url):
        return True

    def fetch(self, url, **kw):
        self.calls.append(url)
        if url in self.fail:
            raise FetchError(self.fail[url], url)
        if url in self.pages:
            ctype, body = self.pages[url]
            return FetchResult(url, url, 200, ctype, body if isinstance(body, bytes)
                               else body.encode(), [url])
        raise FetchError("http_status", "404")


def archived(url=URL, html=FULL):
    api = json.dumps({"archived_snapshots": {"closest": {
        "available": True, "status": "200", "timestamp": TS,
        "url": f"http://web.archive.org/web/{TS}/{url}"}}})
    return {ARCHIVE_API + quote(url, safe=""): ("application/json", api),
            SNAP: ("text/html", html)}


class FakeRenderer:
    def __init__(self, html=FULL, lands_on=None):
        self.html, self.calls, self.lands_on, self.uas = html, [], lands_on, []

    def render(self, url, *, allow, allow_navigation, user_agent, max_bytes, timeout):
        self.calls.append(url)
        self.uas.append(user_agent)
        return self.html, self.lands_on or url


def run_for(tmp_path, crawler, renderer=None, url=URL):
    run = create_run(tmp_path / "runs", "t", models=["opus", "sonnet"], backend="x", lang="en")
    write_json(run.path("00-intake.json"), {"purpose": "audit", "audience": {}, "lang": "en",
                                            "targets": [{"kind": "url", "value": url}]})
    m = run_sources(run, crawler, renderer=renderer)
    return run, m["items"][0]


def text_of(run):
    return " ".join(s["text"] for s in read_json(run.path("01-sources/segments.json"))["D1"])


# ---- step 1: bounded retries ------------------------------------------------

class Seq(BaseHTTPRequestHandler):
    replies = []

    def do_GET(self):
        if self.path == "/robots.txt":
            status, headers, body = 404, {}, b""
        else:
            status, headers, body = Seq.replies.pop(0) if len(Seq.replies) > 1 else Seq.replies[0]
        self.send_response(status)
        for k, v in dict({"Content-Type": "text/html"}, **headers).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def seq_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Seq)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


# @S-source-acquisition-024
def test_retry_after_then_success_and_bounded_failure(seq_server):
    waits = []
    c = Crawler(resolver=lambda h, p: ["127.0.0.1"], sleep=waits.append, min_interval=0,
                _allow_hosts_for_tests=frozenset({"pub.example"}))
    Seq.replies = [(429, {"Retry-After": "2"}, b""), (200, {}, b"<p>ok</p>")]
    res = c.fetch(f"http://pub.example:{seq_server}/a")
    assert res.status == 200 and waits == [2.0]
    waits.clear()
    Seq.replies = [(503, {}, b"down")]
    with pytest.raises(FetchError) as e:
        c.fetch(f"http://pub.example:{seq_server}/b")
    assert e.value.reason == "http_status" and waits == [1.0, 2.0]
    waits.clear()
    Seq.replies = [(429, {"Retry-After": "86400"}, b""), (200, {}, b"<p>ok</p>")]
    c.fetch(f"http://pub.example:{seq_server}/c")
    assert waits == [30.0]  # capped


# ---- what never falls back -------------------------------------------------

# @S-source-acquisition-025
@pytest.mark.parametrize("reason", ["robots", "site_profile_blocked", "blocked_address",
                                    "login_or_paywall"])
def test_refusals_never_fall_back(tmp_path, reason):
    c = FakeCrawler(pages=archived(), fail={URL: reason})
    r = FakeRenderer()
    run, item = run_for(tmp_path, c, r)
    assert item["status"] == "failed" and item["reason"] == reason
    assert c.calls == [URL] and r.calls == []


# ---- step 2: the browser ---------------------------------------------------

# @S-source-acquisition-026
def test_thin_page_is_rendered(tmp_path):
    c = FakeCrawler(pages={URL: ("text/html", THIN)})
    r = FakeRenderer()
    run, item = run_for(tmp_path, c, r)
    assert item["via"] == "render" and item["fell_back_from"] == "thin_page"
    assert r.calls == [URL] and "Paragraph 7 of the full article" in text_of(run)
    assert run.path("01-sources/raw/D1.rendered.html").exists()
    assert run.path("01-sources/raw/D1.html").read_bytes() == THIN
    c = FakeCrawler(pages={URL: ("text/html", EMPTY)})
    run, item = run_for(tmp_path / "empty", c, FakeRenderer())
    assert item["via"] == "render" and item["fell_back_from"] == "empty_page"


# @S-source-acquisition-027
def test_browser_requests_checked_like_the_crawler():
    def resolver(host, port):
        return {"public.example": ["93.184.216.34"], "127.0.0.1": ["127.0.0.1"],
                "169.254.169.254": ["169.254.169.254"]}[host]
    c = Crawler(resolver=resolver)
    allowed = [u for u in ("http://127.0.0.1/x", "http://169.254.169.254/",
                           "file:///etc/passwd", "https://user:pw@public.example/a.js",
                           "https://public.example/a.js") if c.request_allowed(u)]
    assert allowed == ["https://public.example/a.js"]


# ---- step 3: AMP, then the archive ------------------------------------------

# @S-source-acquisition-028
def test_without_browser_amp_then_archive(tmp_path):
    amp_page = THIN.replace(b"<html>", b"<html><head><link rel='amphtml' href='/amp/story'></head>")
    c = FakeCrawler(pages={URL: ("text/html", amp_page),
                           "https://news.example/amp/story": ("text/html", FULL)})
    run, item = run_for(tmp_path / "a", c)
    assert item["via"] == "amp" and "Paragraph 3" in text_of(run)
    c = FakeCrawler(pages=dict(archived(), **{URL: ("text/html", THIN)}))
    run, item = run_for(tmp_path / "b", c)
    assert item["via"] == "archive" and item["archived_at"] == "2026-01-02"
    c = FakeCrawler(pages={URL: ("text/html", THIN)})
    run, item = run_for(tmp_path / "c", c)
    assert item["via"] == "direct" and "no_browser_installed" in item["warning"]
    c = FakeCrawler(pages={URL: ("text/html", EMPTY)})
    run, item = run_for(tmp_path / "d", c)
    assert item["status"] == "failed" and item["reason"] == "empty_page"


# @S-source-acquisition-029
def test_failed_fetch_uses_dated_archive_copy_never_browser_for_challenge(tmp_path):
    from ant_peer_review.i18n import T
    from ant_peer_review.report import sources_rows
    r = FakeRenderer()
    c = FakeCrawler(pages=archived(), fail={URL: "http_status"})
    run, item = run_for(tmp_path / "a", c, r)
    assert item["status"] == "ok" and item["via"] == "archive"
    assert item["fell_back_from"] == "http_status" and item["archived_at"] == "2026-01-02"
    assert item["archive_url"] == f"https://web.archive.org/web/{TS}/{URL}"
    c = FakeCrawler(pages=dict(archived(), **{URL: ("text/html", CHALLENGE)}))
    run, item = run_for(tmp_path / "b", c, r)
    assert item["via"] == "archive" and item["fell_back_from"] == "blocked_by_challenge"
    assert r.calls == []
    rows = "\n".join(sources_rows(T("en"), read_json(run.path("01-sources/manifest.json"))))
    assert "Wayback Machine copy 2026-01-02" in rows and "blocked\\_by\\_challenge" in rows


# ---- step 4: the user pastes --------------------------------------------------

# @S-source-acquisition-030
def test_failed_url_replaced_by_pasted_text(tmp_path):
    from ant_peer_review.pipeline import Ctx, Stop, ph_sources
    from ant_peer_review.store import Config
    from ant_peer_review.ui import ScriptedIO
    c = FakeCrawler(fail={URL: "http_status"})
    run, _ = run_for(tmp_path / "i", c)
    io = ScriptedIO(["2", "Pasted line one.", "Pasted line two.", "/done"])
    ctx = Ctx(io=io, store=None, cfg=Config(), backend=None, models=["opus", "sonnet"], lang="en",
              interactive=True, crawler=c, options={"renderer": None})
    ph_sources(run, ctx)
    item = read_json(run.path("01-sources/manifest.json"))["items"][0]
    assert item["status"] == "ok" and item["via"] == "paste"
    assert item["docs"][0]["origin"] == URL
    assert read_json(run.path("00-intake.json"))["targets"][0]["pasted_for"] == URL
    assert "Pasted line two." in text_of(run)
    run2, _ = run_for(tmp_path / "n", c)
    io = ScriptedIO([])
    ctx = Ctx(io=io, store=None, cfg=Config(), backend=None, models=["opus", "sonnet"], lang="en",
              interactive=False, crawler=c, options={"renderer": None})
    with pytest.raises(Stop):
        ph_sources(run2, ctx)
    assert "--target <file>" in io.text


# @S-source-acquisition-031
def test_needs_js_profile_renders_and_lesson_offers_it(tmp_path):
    long_static = FULL.replace("Paragraph", "Static")
    c = FakeCrawler(pages={URL: ("text/html", long_static)},
                    profiles={"news.example": {"needs_js": True}})
    run, item = run_for(tmp_path, c, FakeRenderer(FULL.replace("</article>", "<p>Rendered extra paragraph.</p></article>")))
    assert item["via"] == "render" and item["fell_back_from"] == "needs_js"
    assert "Rendered extra paragraph." in text_of(run)
    from ant_peer_review.i18n import T
    from ant_peer_review.lessons import add_lesson, promote_if_repeated
    from ant_peer_review.store import Store
    from ant_peer_review.ui import ScriptedIO
    store = Store(tmp_path / "home")
    for _ in range(2):
        lid = add_lesson(store, "empty page", area="crawl/news.example", cause="c", rule="r",
                         enforced="judgment")
    io = ScriptedIO(["2"])
    promote_if_repeated(io, T("en"), store, lid, "crawl/news.example")
    assert read_json(store.site_profiles)["news.example"]["needs_js"] is True


# ---- tier-3 review findings -------------------------------------------------

# @S-source-acquisition-032
def test_hostile_retry_after_uses_default_backoff(seq_server):
    waits = []
    c = Crawler(resolver=lambda h, p: ["127.0.0.1"], sleep=waits.append, min_interval=0,
                _allow_hosts_for_tests=frozenset({"pub.example"}))
    Seq.replies = [(429, {"Retry-After": "\u00b2".encode("latin-1").decode("latin-1")}, b""),
                   (200, {}, b"<p>ok</p>")]
    assert c.fetch(f"http://pub.example:{seq_server}/a").status == 200 and waits == [1.0]


# @S-source-acquisition-033
@pytest.mark.parametrize("status,falls_back", [("401", False), ("402", False), ("451", False),
                                               ("403", True)])
def test_auth_payment_legal_statuses_never_fall_back(tmp_path, status, falls_back):
    class C(FakeCrawler):
        def fetch(self, url, **kw):
            if url == URL:
                self.calls.append(url)
                raise FetchError("http_status", status)
            return super().fetch(url, **kw)
    c = C(pages=archived())
    run, item = run_for(tmp_path, c)
    assert (item["status"] == "ok") is falls_back
    assert any(u.startswith(ARCHIVE_API) for u in c.calls) is falls_back


# @S-source-acquisition-034
def test_secret_url_never_sent_to_archive(tmp_path):
    url = "https://news.example/story?token=SECRET"
    c = FakeCrawler(pages=archived(url), fail={url: "http_status"})
    run, item = run_for(tmp_path, c, url=url)
    assert item["status"] == "failed" and c.calls == [url]
    stored = "".join(p.read_text(errors="ignore") for p in run.root.rglob("*")
                     if p.is_file() and p.name != "00-intake.json")  # the user's own input
    assert "SECRET" not in stored


# @S-source-acquisition-035
def test_paywall_seen_by_browser_or_amp_stops_the_chain(tmp_path):
    wall = "<html><body><h1>Members only</h1><p>Subscribe to continue reading.</p></body></html>"
    c = FakeCrawler(pages=dict(archived(), **{URL: ("text/html", THIN)}))
    run, item = run_for(tmp_path / "r", c, FakeRenderer(wall))
    assert item["reason"] == "login_or_paywall"
    assert not any(u.startswith(ARCHIVE_API) for u in c.calls)
    amp_page = THIN.replace(b"<html>", b"<html><head><link rel='amphtml' href='/amp'></head>")
    c = FakeCrawler(pages=dict(archived(), **{URL: ("text/html", amp_page),
                                               "https://news.example/amp": ("text/html", wall)}))
    run, item = run_for(tmp_path / "a", c)
    assert item["reason"] == "login_or_paywall"
    assert not any(u.startswith(ARCHIVE_API) for u in c.calls)


# @S-source-acquisition-036
def test_browser_landing_is_checked_recorded_and_uses_our_ua(tmp_path):
    from ant_peer_review.sources.crawler import DEFAULT_UA
    denied = "https://other.example/private"

    class C(FakeCrawler):
        def preflight(self, url):
            if url == denied:
                raise FetchError("robots", url)
            return DEFAULT_UA
    r = FakeRenderer(lands_on=denied)
    run, item = run_for(tmp_path / "d", C(pages={URL: ("text/html", THIN)}), r)
    assert item.get("via") != "render" and r.uas == [DEFAULT_UA]
    landed = "https://news.example/story/full"
    run, item = run_for(tmp_path / "ok", C(pages={URL: ("text/html", THIN)}),
                        FakeRenderer(lands_on=landed))
    assert item["via"] == "render" and item["docs"][0]["origin"] == landed


# @S-source-acquisition-037
def test_archive_replaces_live_page_only_when_clearly_longer(tmp_path):
    def page(n):
        return "<html><body><article><p>" + ("w" * n) + "</p></article></body></html>"
    c = FakeCrawler(pages=dict(archived(html=page(250)), **{URL: ("text/html", page(150))}))
    run, item = run_for(tmp_path / "a", c)
    assert item["via"] == "direct" and "thin_page" in item["warning"]
    c = FakeCrawler(pages=dict(archived(html=page(400)), **{URL: ("text/html", page(150))}))
    run, item = run_for(tmp_path / "b", c)
    assert item["via"] == "archive"


# @S-source-acquisition-038
def test_retried_items_keep_raw_matching_hash(tmp_path):
    import hashlib
    run = create_run(tmp_path / "runs", "t", models=["opus", "sonnet"], backend="x", lang="en")
    write_json(run.path("00-intake.json"), {"purpose": "audit", "audience": {}, "lang": "en",
                                            "targets": [{"kind": "url", "value": URL}]})
    run_sources(run, FakeCrawler(pages={URL: ("text/html", EMPTY)}),
                renderer=FakeRenderer("<html><body><p>still loading</p></body></html>"))
    assert not run.path("01-sources/raw/D1.rendered.html").exists()
    m = run_sources(run, FakeCrawler(pages={URL: ("text/html", FULL)}))
    d = m["items"][0]["docs"][0]
    raw = run.path("01-sources/raw/" + d["raw"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == d["sha256"] and b"Paragraph 7" in raw


# @S-source-acquisition-039
def test_unreadable_archive_answer_keeps_first_reason(tmp_path):
    bad_ts = {ARCHIVE_API + quote(URL, safe=""): ("application/json", json.dumps(
        {"archived_snapshots": {"closest": {"available": True, "status": "200",
                                            "timestamp": "latest"}}})),
              f"https://web.archive.org/web/latestid_/{URL}": ("text/html", FULL)}
    run, item = run_for(tmp_path / "t", FakeCrawler(pages=bad_ts, fail={URL: "http_status"}))
    assert item["reason"] == "http_status"
    pdf = dict(archived(), **{SNAP: ("application/pdf", b"%PDF-1.4 broken")})
    run, item = run_for(tmp_path / "p", FakeCrawler(pages=pdf, fail={URL: "http_status"}))
    assert item["reason"] == "http_status"


# @S-source-acquisition-040
def test_no_render_flag_and_contact_joins_our_ua(tmp_path, monkeypatch):
    import ant_peer_review.cli as cli
    from ant_peer_review.i18n import T
    from ant_peer_review.lessons import add_lesson, promote_if_repeated
    from ant_peer_review.sources.crawler import DEFAULT_UA
    from ant_peer_review.store import Store
    from ant_peer_review.ui import ScriptedIO
    seen = {}
    import ant_peer_review.pipeline as pipeline
    monkeypatch.setitem(pipeline.PHASE_FUNCS, "sources",
                        lambda run, ctx: seen.setdefault("opts", dict(ctx.options)) and None)
    store = Store(tmp_path / "home")
    cli.main(["new", "--yes", "--backend", "fake", "--no-render", "--target", "plain text"],
             io=ScriptedIO([]), store=store)
    assert seen["opts"].get("renderer", "missing") is None
    for _ in range(2):
        lid = add_lesson(store, "t", area="crawl/news.example", cause="c", rule="r",
                         enforced="judgment")
    promote_if_repeated(ScriptedIO(["3", "ed@acme.example"]), T("en"), store, lid,
                        "crawl/news.example")
    assert read_json(store.site_profiles)["news.example"]["user_agent"] == \
        DEFAULT_UA + " ed@acme.example"

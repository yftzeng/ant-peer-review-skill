import pytest

from ant_peer_review.jsonio import read_json, write_json
from ant_peer_review.sources.acquire import run_sources
from ant_peer_review.sources.crawler import FetchError, FetchResult
from ant_peer_review.workspace import create_run

LONG = "<p>" + "A real paragraph of article text with enough words. " * 30 + "</p>"
PAGES = {
    "https://ex.example/challenge": "<html><head><title>Just a moment...</title></head><body>"
                                    "<div id='cf-chl-widget'></div><script src='/cdn-cgi/challenge-platform/x.js'>"
                                    "</script><p>Checking your browser.</p></body></html>",
    "https://ex.example/article": "<html><body><script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'>"
                                  f"</script><article><h1>Title</h1>{LONG}</article></body></html>",
    "https://ex.example/gone": "<html><head><title>404 Not Found</title></head><body><h1>Page not found</h1>"
                               "<p>Sorry.</p></body></html>",
    "https://ex.example/wall": "<html><body><h1>Members only</h1><p>Sign in to continue reading this "
                               "story.</p></body></html>",
    "https://ex.example/empty": "<html><body><div></div></body></html>",
}


class Fake:
    def __init__(self):
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        base = url.split("?")[0]
        return FetchResult(url, url, 200, "text/html", PAGES[base].encode(), [url])


def run_with(tmp_path, urls, crawler=None, progress=None):
    run = create_run(tmp_path / "runs", "x", models=["opus", "sonnet"], backend="fake", lang="en")
    write_json(run.path("00-intake.json"), {"purpose": "audit", "audience": {},
                                            "targets": [{"kind": "url", "value": u} for u in urls]})
    return run, run_sources(run, crawler or Fake(), on_progress=progress)


# @S-source-acquisition-020
def test_challenge_page_fails_normal_page_with_script_ok(tmp_path):
    _, m = run_with(tmp_path, ["https://ex.example/challenge", "https://ex.example/article"])
    assert (m["items"][0]["status"], m["items"][0].get("reason")) == ("failed", "blocked_by_challenge")
    assert m["items"][1]["status"] == "ok"


# @S-source-acquisition-021
def test_soft_404_wall_empty(tmp_path):
    _, m = run_with(tmp_path, ["https://ex.example/gone", "https://ex.example/wall",
                               "https://ex.example/empty"])
    assert [i.get("reason") for i in m["items"]] == ["soft_404", "login_or_paywall", "empty_page"]


# @S-source-acquisition-022
def test_secrets_redacted(tmp_path):
    from ant_peer_review.report import render
    from ant_peer_review.rubric import propose
    from ant_peer_review.sources.urls import redact
    assert redact("https://ex.example/feed?token=abc123&page=2") == \
        "https://ex.example/feed?token=REDACTED&page=2"
    seen = []
    run, m = run_with(tmp_path, ["https://ex.example/article?token=abc123&page=2"],
                      progress=lambda e: seen.append(str(e)))
    assert "abc123" not in run.path("01-sources/manifest.json").read_text()
    assert "token=REDACTED&page=2" in run.path("01-sources/manifest.json").read_text()
    write_json(run.path("02-rubric.json"), propose({}))
    cons = {"provenance": [], "warnings": [], "active": [], "scores": {}, "total": 0,
            "grade": "fail", "provisional": False, "split_scores": [], "red_lines": {},
            "findings": [], "unverified_findings": [], "impact_s_curve": None}
    md = render(run, cons, lang="en", version=1, changelog=[])
    assert "abc123" not in md and "token=REDACTED" in md
    assert all("abc123" not in s for s in seen)


# @S-review-panel-020
def test_report_sources_section(tmp_path):
    from ant_peer_review.report import render
    from ant_peer_review.rubric import propose

    class Mixed(Fake):
        def fetch(self, url):
            if "a/3" in url:
                raise FetchError("network", url)
            return super().fetch(url)
    run = create_run(tmp_path / "runs", "x", models=["opus", "sonnet"], backend="fake", lang="en")
    write_json(run.path("00-intake.json"), {"purpose": "audit", "audience": {}, "targets": [
        {"kind": "url", "value": "https://ex.example/article"},
        {"kind": "feed_item", "value": "https://ex.example/a/3", "title": "T",
         "html": "<p>" + "feed text " * 40 + "</p>"},
        {"kind": "url", "value": "https://ex.example/challenge"}]})
    run_sources(run, Mixed())
    write_json(run.path("02-rubric.json"), propose({}))
    cons = {"provenance": [], "warnings": [], "active": [], "scores": {}, "total": 0,
            "grade": "fail", "provisional": False, "split_scores": [], "red_lines": {},
            "findings": [], "unverified_findings": [], "impact_s_curve": None}
    md = render(run, cons, lang="en", version=1, changelog=[])
    sec = md[md.index("## Sources"):]
    assert "D1" in sec and "page" in sec
    assert "D2" in sec and "feed copy, may be lossy" in sec
    assert "blocked_by_challenge" in sec


# @S-cli-014
def test_feed_picker_completeness_note():
    from ant_peer_review.i18n import T
    assert "may show only the latest" in T("en")("feed.pick", n=3)
    assert "3" in T("en")("feed.pick", n=3)

from ant_peer_review.factcheck import check_claim
from ant_peer_review.jsonio import read_json, write_json
from ant_peer_review.sources.acquire import run_sources
from ant_peer_review.workspace import create_run
from helpers import ScriptBackend
from test_factcheck import CLAIM, search_result
from test_fallback import FULL, FakeCrawler

POST = "https://blog.example/post"
OTHER = "https://other.example/a"
TEXT = ("權重空間編程：只改動 0.016% 的權重，MATH-500 從 7.9% 提升到 48.1%。"
        f"詳見 {POST}/ 與 {OTHER}，還有 https://c.example/1 https://d.example/2 https://e.example/3")
BLOG = ("<html><head><title>Weight-space programming</title></head><body><article>"
        "<p>Intro paragraph about networks and gradient descent, long enough to count as text.</p>"
        "<p>Editing 0.016% of the weights of a 0.8B model, MATH-500 rose from 7.9% to 48.1%.</p>"
        + "".join(f"<p>Unrelated paragraph {i} about something else entirely, with more words.</p>"
                  for i in range(8)) + "</article></body></html>")


def run_with(tmp_path, targets, crawler):
    run = create_run(tmp_path / "runs", "t", models=["opus"], backend="x", lang="en")
    write_json(run.path("00-intake.json"), {"purpose": "audit", "audience": {}, "lang": "en",
                                            "targets": targets})
    return run, run_sources(run, crawler)


# @S-source-acquisition-050
def test_url_in_text_is_fetched_as_a_cited_source(tmp_path):
    pages = {POST + "/": ("text/html", BLOG), OTHER: ("text/html", FULL)}
    c = FakeCrawler(pages=pages, fail={"https://c.example/1": "http_status"})
    run, m = run_with(tmp_path, [{"kind": "text", "value": TEXT}, {"kind": "url", "value": OTHER}], c)
    assert c.calls.count(OTHER) == 1                                   # already a target
    cited = m["cited"]
    assert [x["url"] for x in cited] == [POST + "/", "https://c.example/1", "https://d.example/2"]
    assert [x["status"] for x in cited] == ["ok", "failed", "failed"]
    assert "https://e.example/3" not in c.calls                        # at most 3
    body = run.path(cited[0]["file"]).read_text()
    assert cited[0]["file"] == "01-sources/cited/R1.md" and "rose from 7.9% to 48.1%" in body
    segs = read_json(run.path("01-sources/segments.json"))
    assert sorted(segs) == ["D1", "D2"] and "48.1% to" not in str(segs)
    from ant_peer_review.review import article_view
    assert "rose from 7.9%" not in article_view(run)
    from ant_peer_review.share import documents
    art, refs = documents(run)
    assert "rose from 7.9% to 48.1%" in refs and "rose from" not in art


# @S-factcheck-ledger-017
def test_checker_gets_matching_paragraphs_of_cited_sources():
    cited = [{"id": "R1", "url": POST + "/", "status": "ok",
              "text": "Intro about networks.\n\nEditing 0.016% of weights, MATH-500 rose from 7.9% to 48.1%.\n\n"
                      + "\n\n".join(f"Unrelated paragraph {i}." for i in range(30))}]
    claim = dict(CLAIM, text="MATH-500 從 7.9% 提升到 48.1%")
    b = ScriptBackend({("sonnet", "factcheck"): search_result("supported", [POST + "/", "https://x.example"], [])})
    c = check_claim(b, "sonnet", claim, "ctx", "en", cited=cited)
    p = b.calls[0]["prompt"]
    assert "rose from 7.9% to 48.1%" in p and "Unrelated paragraph 5" not in p
    assert "not neutral evidence" in p and POST in p
    assert c["status"] == "supported" and [s["url"] for s in c["sources"]] == [POST + "/"]


# @S-source-acquisition-052 the run 20261106-0304 case
def test_cited_url_stops_at_chinese_text():
    from ant_peer_review.sources.acquire import cited_urls
    text = "我們新的論文：https://arxiv.org/abs/2610.37741这篇论文，首次证明预训练投毒"
    assert cited_urls({"targets": [{"kind": "text", "value": text}]}) == \
        ["https://arxiv.org/abs/2610.37741"]
    assert cited_urls({"targets": [{"kind": "text", "value":
                                     "見 https://zh.wikipedia.org/wiki/%E8%87%BA%E7%81%A3 一文"}]}) \
        == ["https://zh.wikipedia.org/wiki/%E8%87%BA%E7%81%A3"]

from ant_peer_review.backends.base import Result
from ant_peer_review.factcheck import check_claim
from ant_peer_review.jsonio import read_json, write_json
from ant_peer_review.report import lint_report
from helpers import ScriptBackend, make_run, ok, review_data


def finding(fid, **kw):
    f = {"id": fid, "anchor": "D1.P01.S1", "observation": "obs", "standard": "std",
         "why_it_matters": "why", "action": "act"}
    f.update(kw)
    return f


def lint(*findings):
    return lint_report({"findings": list(findings), "unverified_findings": []}, "# R\n", [])


# @S-review-panel-016
def test_tone_lint():
    probs = lint(finding("F01", observation="This is sloppy work."),
                 finding("F02", why_it_matters="作者根本不懂這個主題"),
                 finding("F03", action="I am the editor and require changes"),
                 finding("F04", action="We recommend rejection of this piece."))
    text = "\n".join(probs)
    for fid in ("F01", "F02", "F03", "F04"):
        assert fid in text, (fid, probs)
    assert lint(finding("F05", observation="The argument in P02 lacks a source.")) == []


# @S-review-panel-017
def test_absence_needs_checked_surfaces():
    probs = lint(finding("F01", anchor="absence: whole piece - expected sources"))
    assert any("absence without checked surfaces" in p for p in probs)
    assert lint(finding("F02", anchor="absence: whole piece - expected sources; checked: body, footnotes")) == []


# @S-factcheck-ledger-011
def test_sources_have_accessed_at(tmp_path):
    res = Result(model="", model_id="", data={
        "status": "supported", "reason": "", "sources": [{"url": "https://a.example/x",
                                                          "supporting_excerpt": "e"}]},
        tool_calls=[{"name": "WebSearch", "input": {}}], tool_results=["https://a.example/x"])
    c = check_claim(ScriptBackend({("s", "factcheck"): res}), "s",
                    {"id": "C01", "anchor": "D1.P01", "text": "t", "type": "other",
                     "status": "pending", "reason": "", "sources": [], "refs": []}, "", "en")
    acc = c["sources"][0]["accessed_at"]
    assert acc[:4].isdigit() and "T" in acc
    from ant_peer_review.report import source_urls
    assert acc[:10] in source_urls(c["sources"])


# @S-revision-007
def test_coverage_table(tmp_path):
    from ant_peer_review.revision import run_revision
    run = make_run(tmp_path, text="# T\n\nPara two text.\n\nPara three text.")
    for m in ("opus", "sonnet"):
        write_json(run.path(f"03-reviews/{m}.json"), ok(m, review_data()))
    base = {"severity": "minor", "observation": "o", "standard": "s", "why_it_matters": "w",
            "action": "a", "label": "SINGLE", "supporters": ["opus"], "dissent": [],
            "members": ["opus:I1"], "dimension": "micro"}
    write_json(run.path("05-consensus.json"), {"unverified_findings": [], "findings": [
        dict(base, id="F01", anchor="D1.P03.S1", level="macro", severity="major"),
        dict(base, id="F02", anchor="D1.P02.S1", level="micro"),
        dict(base, id="F03", anchor="D1.P03.S1", level="micro")]})
    b = ScriptBackend({
        ("opus", "revise_a"): {"paragraphs": [{"id": "D1.P02", "text": "Para two, fixed."}],
                               "corrections": []},
        ("opus", "revise_b"): {"headline_options": [], "notes": "",
                               "paragraphs": [{"id": "D1.P03", "text": "New close.",
                                               "addresses": ["F01"]}]},
        ("sonnet", "rereview"): {"verdicts": []}})
    out = run_revision(run, b, ["opus", "sonnet"], "en", say=lambda *_: None)
    cov = read_json(run.path("07-revision/coverage.json"))
    assert cov["by_finding"] == {"F01": "B", "F02": "A", "F03": "none"}
    assert out["coverage"] == {"A": 1, "B": 1, "both": 0, "none": 1}

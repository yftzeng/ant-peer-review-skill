from ant_peer_review.backends.base import BackendError
from ant_peer_review.decision import run_decision
from ant_peer_review.deliver import STYLES, length_target
from ant_peer_review.jsonio import read_json, write_json
from ant_peer_review.ui import ScriptedIO
from helpers import ScriptBackend, ok, review_data
from test_decision import M, TH, setup

SUMMARY = {"summary": "A short piece with one structural gap.",
           "key_points": [{"text": "The close does not return to the claim.", "findings": ["F01"]},
                          {"text": "Invented point.", "findings": ["F99"]}]}


def replies(styles=STYLES, critical="The text needs work on its ending."):
    return {"replies": [{"style": s, "text": critical if s == "critical" else f"Dear author ({s})."}
                        for s in styles]}


def backend(summary=SUMMARY, reply=None):
    return ScriptBackend({("*", "summary"): summary, ("*", "reply"): reply or replies()})


def with_issue(tmp_path):
    run, store = setup(tmp_path)
    write_json(run.path("03-reviews/opus.json"), ok("opus", review_data(issues=[{"id": "I1"}])))
    from ant_peer_review.refresh import compute_consensus
    assert compute_consensus(run, M, TH)["findings"][0]["id"] == "F01"
    return run, store


def decide(run, store, io=None, **kw):
    return run_decision(io, run, store, models=M, lang="en", thresholds=TH, min_repeats=3, **kw)


# @S-decision-009
def test_review_gathers_every_check(tmp_path):
    run, store = with_issue(tmp_path)
    decide(run, store, None, choice="A", backend=backend(), reply_styles=[])
    md = run.path("review.md").read_text()
    for want in ("## Verdict", "## Summary", "A short piece with one structural gap.", "## Key points",
                 "The close does not return to the claim. (F01)", "## Checks", "Structure",
                 "Serious factual error", "Fact-check", "Injection scan", "Report lint",
                 "## Anchored issues", "## Review process", "## Detail files", "06-report.v"):
        assert want in md, want
    checks = md.split("## Checks", 1)[1].split("\n## ", 1)[0]
    assert sum(1 for ln in checks.splitlines() if ln.startswith("| ")) == 1 + 4 + 6 + 3  # header + rows


# @S-decision-010
def test_key_points_need_real_findings_and_summary_can_fail(tmp_path):
    run, store = with_issue(tmp_path)
    decide(run, store, None, choice="A", backend=backend(), reply_styles=[])
    md = run.path("review.md").read_text()
    assert "Invented point." not in md and "F99" not in md
    b = ScriptBackend({("*", "summary"): BackendError("down", reason="offline")})
    decide(run, store, None, choice="A", backend=b, reply_styles=[])
    md = run.path("review.md").read_text()
    assert "summary is missing" in md and "## Checks" in md


# @S-decision-011
def test_audit_writes_one_reply_per_ticked_style(tmp_path):
    run, store = with_issue(tmp_path)
    b = backend()
    decide(run, store, ScriptedIO(["1", ""]), backend=b)        # plan A, keep all five ticked
    for s in ("appreciative", "empathetic", "pragmatic", "socratic", "critical"):
        assert run.path(f"reply-{s}.md").read_text().strip(), s
    call = next(c for c in b.calls if c["task"] == "reply")
    assert "same language as the article" in call["system"]
    for s in STYLES:
        assert f"{s}: about {length_target(s, read_json(run.path('05-consensus.json')))}" in call["prompt"]
    assert length_target("critical", {"findings": [{"severity": "critical"}] * 4}) > \
        length_target("critical", {"findings": [{"severity": "minor"}]}) > \
        length_target("appreciative", {"findings": [{"severity": "minor"}]})

    for p in run.root.glob("reply-*.md"):
        p.unlink()
    decide(run, store, ScriptedIO(["1", "1 2 3", ""]),           # untick the first three
           backend=backend(reply=replies(["socratic", "critical"])))
    assert sorted(p.name for p in run.root.glob("reply-*.md")) == \
        ["reply-critical.md", "reply-socratic.md"]

    for p in run.root.glob("reply-*.md"):
        p.unlink()
    intake = read_json(run.path("00-intake.json"))
    write_json(run.path("00-intake.json"), dict(intake, purpose="drafting"))
    b = backend()
    decide(run, store, ScriptedIO(["1"]), backend=b)
    assert list(run.root.glob("reply-*.md")) == [] and all(c["task"] != "reply" for c in b.calls)


# @S-decision-012
def test_replies_by_argument(tmp_path):
    run, store = with_issue(tmp_path)
    decide(run, store, None, choice="A", backend=backend())
    assert len(list(run.root.glob("reply-*.md"))) == 5
    for p in run.root.glob("reply-*.md"):
        p.unlink()
    decide(run, store, None, choice="A", backend=backend(reply=replies(["pragmatic", "socratic"])),
           reply_styles=["pragmatic", "socratic"])
    assert sorted(p.name for p in run.root.glob("reply-*.md")) == \
        ["reply-pragmatic.md", "reply-socratic.md"]


# @S-decision-013
def test_reply_attacking_the_author_is_flagged(tmp_path):
    run, store = with_issue(tmp_path)
    io = ScriptedIO([])
    decide(run, store, io, choice="A", backend=backend(reply=replies(
        critical="Frankly the author is clueless about this.")), reply_styles=["critical"])
    text = run.path("reply-critical.md").read_text()
    assert text.startswith("> ⚠") and "clueless" in text
    assert "critical" in io.text and "tone" in io.text

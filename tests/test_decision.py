from ant_peer_review.decision import run_decision
from ant_peer_review.jsonio import append_jsonl, read_json, write_json, write_text_atomic
from ant_peer_review.refresh import compute_consensus
from ant_peer_review.report import latest_version, write_report
from ant_peer_review.store import Store
from ant_peer_review.ui import ScriptedIO
from helpers import make_run, ok, review_data

TH = {"excellent": 85, "good": 70, "revise": 60}
M = ["opus", "sonnet"]


def setup(tmp_path, flags_opus=(), brand=None, corrections=()):
    run = make_run(tmp_path)
    if brand:
        intake = read_json(run.path("00-intake.json"))
        intake["brand"] = brand
        write_json(run.path("00-intake.json"), intake)
    write_json(run.path("03-reviews/opus.json"), ok("opus", review_data(flags=list(flags_opus))))
    write_json(run.path("03-reviews/sonnet.json"), ok("sonnet", review_data()))
    write_report(run, compute_consensus(run, M, TH), lang="en")
    write_text_atomic(run.path("07-revision/A.md"), "A text\n")
    write_text_atomic(run.path("07-revision/B.md"), "B text\n")
    write_json(run.path("07-revision/corrections.json"), list(corrections))
    return run, Store(tmp_path / "home")


def decide(run, store, io=None, **kw):
    return run_decision(io, run, store, models=M, lang="en", thresholds=TH, min_repeats=3, **kw)


# @S-decision-001
def test_ruling_recorded_and_new_report(tmp_path):
    run, store = setup(tmp_path, flags_opus=["pr_landmine"])
    io = ScriptedIO(["2", "2"])  # dismiss, then choose B
    decide(run, store, io)
    assert read_json(run.path("08-decision.json"))["rulings"] == {"pr_landmine": "dismissed"}
    assert latest_version(run) == 2
    assert "Dismissed" in run.path("06-report.v2.md").read_text()


# @S-decision-002
def test_choice_becomes_final(tmp_path):
    run, store = setup(tmp_path)
    decide(run, store, ScriptedIO(["2"]))
    assert run.path("audit.md").read_text() == "B text\n"
    dec = read_json(run.path("08-decision.json"))
    assert dec["choice"] == "B" and dec["final"].endswith("audit.md")
    intake = read_json(run.path("00-intake.json"))
    write_json(run.path("00-intake.json"), dict(intake, purpose="drafting"))
    decide(run, store, ScriptedIO(["2"]))
    assert run.path("draft.md").read_text() == "B text\n"


ACME = [{"from": "Acme Corp", "to": "ACME", "category": "name"}]


def _seed(store):
    for r in ("old-1", "old-2"):
        append_jsonl(store.corrections_log, {"brand": "acme", "run": r, "from": "Acme Corp",
                                             "to": "ACME", "category": "name"})


# @S-decision-003
def test_recurring_correction_proposed_and_written(tmp_path):
    run, store = setup(tmp_path, brand="acme", corrections=ACME)
    _seed(store)
    decide(run, store, ScriptedIO(["1", "y"]))
    guide = (store.style_guides / "acme.md").read_text()
    assert '"Acme Corp" -> "ACME"' in guide


# @S-decision-004
# @N-decision-001
def test_declined_proposal_writes_nothing(tmp_path):
    run, store = setup(tmp_path, brand="acme", corrections=ACME)
    _seed(store)
    io = ScriptedIO(["1", "n"])
    decide(run, store, io)
    assert "Style Guide" in io.text
    assert not (store.style_guides / "acme.md").exists()


# @S-decision-005
def test_non_interactive(tmp_path):
    run, store = setup(tmp_path, flags_opus=["pr_landmine"])
    dec = decide(run, store, None, choice="A", rulings={"pr_landmine": "confirmed"})
    assert dec["choice"] == "A" and dec["rulings"] == {"pr_landmine": "confirmed"}
    assert read_json(run.path("05-consensus.json"))["grade"] == "fail"
    assert run.path("audit.md").read_text() == "A text\n"


def _unsupported_number(run):
    from ant_peer_review.jsonio import append_jsonl
    append_jsonl(run.path("factcheck/ledger.jsonl"), {
        "id": "C09", "anchor": "D1.P03.S1", "text": "Revenue grew 40% in 2025",
        "type": "number", "status": "unsupported", "reason": "The filing says 12%.",
        "sources": [{"url": "https://example.org/filing", "supporting_excerpt": "grew 12%",
                     "accessed_at": "2026-10-25T08:00:00"}],
        "extracted_by": ["opus"], "refs": ["opus:K1"], "checked_by": "sonnet", "updated_at": ""})
    write_report(run, compute_consensus(run, M, TH), lang="en")


# @S-decision-007
def test_ruling_prompt_shows_context(tmp_path):
    run, store = setup(tmp_path)
    _unsupported_number(run)
    io = ScriptedIO(["2", "2"])  # dismiss, then choose B
    decide(run, store, io)
    out = io.text
    for want in ("Serious factual error",            # the red line
                 "veto",                              # what confirming does
                 "no reviewer flagged",               # why a ruling is needed
                 "Title",                             # the article
                 "D1.P03.S1", "Revenue grew 40% in 2025.",   # where, and the original sentence
                 "The filing says 12%.", "https://example.org/filing",  # checker reason, source
                 "opus: not flagged", "sonnet: not flagged"):   # every reviewer's verdict
        assert want in out, want
    assert read_json(run.path("08-decision.json"))["rulings"] == {"hallucination": "dismissed"}


# @S-decision-008
def test_ruling_can_be_postponed(tmp_path):
    from ant_peer_review.decision import Postponed
    run, store = setup(tmp_path, flags_opus=["pr_landmine"])
    io = ScriptedIO(["3"])  # decide later
    try:
        decide(run, store, io)
        raise AssertionError("expected Postponed")
    except Postponed:
        pass
    assert not run.path("08-decision.json").exists() and not run.path("audit.md").exists()


# @S-decision-008
def test_postponed_ruling_pauses_the_phase(tmp_path):
    from ant_peer_review.pipeline import Ctx, ph_decision, Stop
    from ant_peer_review.store import Config
    run, store = setup(tmp_path, flags_opus=["pr_landmine"])
    io = ScriptedIO(["3"])
    ctx = Ctx(io=io, store=store, cfg=Config(), backend=None, models=M, lang="en",
              interactive=True)
    try:
        ph_decision(run, ctx)
        raise AssertionError("expected Stop")
    except Stop:
        pass
    assert f"ant-peer-review decide {run.id}" in io.text

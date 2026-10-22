import json

import pytest

import ant_peer_review.cli as cli
from ant_peer_review.jsonio import read_json, write_json
from ant_peer_review.refresh import compute_consensus
from ant_peer_review.report import write_report
from ant_peer_review.store import Config, Store
from ant_peer_review.workspace import PHASES, Run, create_run, list_runs
from helpers import ScriptBackend, make_run, ok, review_data
from test_cli import NoAskIO

TH = {"excellent": 85, "good": 70, "revise": 60}
RESPONSE = "Dear editor, F01 fixed and F02 fixed. AUTHOR-RESPONSE-MARKER"


def parent_run(home):
    run = make_run(home, text="# Old\n\nOld para one.\n\nOld para two.")
    rub = read_json(run.path("02-rubric.json"))
    for d, w in zip(rub["dimensions"], (40, 20, 20, 20)):
        d["weight"] = w
    write_json(run.path("02-rubric.json"), rub)
    for m in ("opus", "sonnet"):
        write_json(run.path(f"03-reviews/{m}.json"), ok(m, review_data(issues=[
            {"id": "I1", "anchor": "D1.P02.S1", "observation": "OBS-ONE", "level": "macro"},
            {"id": "I2", "anchor": "D1.P03.S1", "observation": "OBS-TWO", "level": "micro",
             "severity": "minor"}])))
    write_json(run.path("04-debate/sonnet.json"), {"model": "sonnet", "status": "ok", "data": {
        "responses": [{"target": "opus:I1", "position": "corroborate", "evidence": "",
                       "duplicate_of": "I1"},
                      {"target": "opus:I2", "position": "corroborate", "evidence": "",
                       "duplicate_of": "I2"}]}})
    cons = compute_consensus(run, ["opus", "sonnet"], TH)
    write_report(run, cons, lang="en")
    for ph in PHASES:
        run.mark(ph, "done")
    return run, [f["id"] for f in cons["findings"]]


def backend(verdicts_by_model, claims=None):
    def rc(model):
        return lambda p: {"verdicts": [{"finding": f, "verdict": v, "evidence": "D1.P02.S1",
                                        "note": ""} for f, v in verdicts_by_model[model].items()]}
    h = {("*", "review"): review_data(), ("*", "debate"): {"responses": []},
         ("*", "factcheck"): {"status": "cannot_verify", "reason": "no_source", "sources": []},
         ("*", "revise_a"): {"paragraphs": [], "corrections": []},
         ("*", "revise_b"): {"headline_options": [], "paragraphs": [], "notes": ""},
         ("*", "rereview"): {"verdicts": []}}
    for m in verdicts_by_model:
        h[(m, "recheck")] = rc(m)
    if claims is not None:
        h[("*", "recheck_claims")] = claims
    return ScriptBackend(h)


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    store = Store(home)
    store.save_config(Config())
    return store, home, monkeypatch


def run_recheck(store, monkeypatch, b, extra=()):
    monkeypatch.setattr(cli, "get_backend", lambda name: b)
    return cli.main(["recheck", *extra], io=NoAskIO(), store=store)


# @S-recheck-001
def test_linked_run_keeps_yardstick(env):
    store, home, mp = env
    parent, fids = parent_run(home)
    b = backend({"opus": {f: "FULLY" for f in fids}, "sonnet": {f: "FULLY" for f in fids}})
    run_recheck(store, mp, b, [parent.id, "--target", "# New\n\nNew para one.", "--yes"])
    child = [r for r in list_runs(store.runs_dir) if r.id != parent.id][0]
    intake = read_json(child.path("00-intake.json"))
    assert intake["parent"] == parent.id
    assert intake["audience"] == read_json(parent.path("00-intake.json"))["audience"]
    assert child.settings()[0] == ["opus", "sonnet"]
    assert read_json(child.path("02-rubric.json")) == read_json(parent.path("02-rubric.json"))


# @S-recheck-002
# @N-recheck-001
def test_gate1_blind_to_response(env, tmp_path):
    store, home, mp = env
    parent, fids = parent_run(home)
    resp = tmp_path / "response.md"
    resp.write_text(RESPONSE)
    b = backend({"opus": {f: "FULLY" for f in fids}, "sonnet": {f: "FULLY" for f in fids}},
                claims={"claims": []})
    run_recheck(store, mp, b, [parent.id, "--target", "# New\n\nNEW-TEXT here.", "--yes",
                               "--response", str(resp)])
    gate1 = [c for c in b.calls if c["task"] == "recheck"]
    assert {c["model"] for c in gate1} == {"opus", "sonnet"}
    for c in gate1:
        assert "OBS-ONE" in c["prompt"] and "OBS-TWO" in c["prompt"] and "NEW-TEXT" in c["prompt"]
        assert "AUTHOR-RESPONSE-MARKER" not in c["prompt"] + c["system"]


# @S-recheck-003
def test_gate2_flags_unsupported_claims(env, tmp_path):
    store, home, mp = env
    parent, (f1, f2) = parent_run(home)
    resp = tmp_path / "response.md"
    resp.write_text(RESPONSE)
    claims = {"claims": [{"finding": f1, "author_claim": "fixed"},
                         {"finding": f2, "author_claim": "fixed"}]}
    b = backend({"opus": {f1: "NOT_ADDRESSED", f2: "FULLY"},
                 "sonnet": {f1: "NOT_ADDRESSED", f2: "FULLY"}}, claims=claims)
    run_recheck(store, mp, b, [parent.id, "--target", "# New\n\nx.", "--yes", "--response", str(resp)])
    child = [r for r in list_runs(store.runs_dir) if r.id != parent.id][0]
    rows = {r["finding"]: r for r in read_json(child.path("05b-recheck.json"))["verdicts"]}
    assert rows[f1]["claim_supported"] is False and rows[f2]["claim_supported"] is True
    g2 = [c for c in b.calls if c["task"] == "recheck_claims"]
    assert len(g2) == 1 and "AUTHOR-RESPONSE-MARKER" in g2[0]["prompt"]
    b2 = backend({"opus": {f1: "FULLY", f2: "FULLY"}, "sonnet": {f1: "FULLY", f2: "FULLY"}})
    run_recheck(store, mp, b2, [parent.id, "--target", "# New\n\ny.", "--yes"])
    assert not [c for c in b2.calls if c["task"] == "recheck_claims"]


# @S-recheck-004
def test_merge_majority_and_unfavourable_ties():
    from ant_peer_review.recheck import merge_verdicts
    assert merge_verdicts({"a": "FULLY", "b": "FULLY", "c": "PARTIALLY"}) == ("FULLY", "majority")
    assert merge_verdicts({"a": "FULLY", "b": "NOT_ADDRESSED", "c": "CANNOT_VERIFY"}) == \
        ("NOT_ADDRESSED", "split")
    assert merge_verdicts({"a": "PARTIALLY", "b": "PARTIALLY"}) == ("PARTIALLY", "unanimous")


# @S-recheck-005
def test_report_has_revision_check_table(env):
    store, home, mp = env
    parent, fids = parent_run(home)
    b = backend({"opus": {fids[0]: "FULLY", fids[1]: "MADE_WORSE"},
                 "sonnet": {fids[0]: "FULLY", fids[1]: "MADE_WORSE"}})
    run_recheck(store, mp, b, [parent.id, "--target", "# New\n\nz.", "--yes"])
    child = [r for r in list_runs(store.runs_dir) if r.id != parent.id][0]
    md = child.path("06-report.v1.md").read_text()
    assert "Revision check" in md and parent.id in md
    assert "MADE_WORSE" in md and "OBS-ONE" in md


# @S-recheck-006
def test_old_state_without_recheck_phase_is_finished(tmp_path):
    run = create_run(tmp_path / "runs", "old", models=["opus", "sonnet"], backend="fake", lang="en")
    for ph in PHASES:
        run.mark(ph, "done")
    st = json.loads(run.state_path.read_text())
    st["phases"].pop("recheck")
    run.state_path.write_text(json.dumps(st))
    assert Run(run.root).is_finished()

from datetime import datetime

import pytest

from ant_peer_review.workspace import PHASES, Run, create_run, unfinished_runs


def mk(tmp_path, slug="x"):
    return create_run(tmp_path / "runs", slug, now=datetime(2026, 10, 22, 9, 30),
                      models=["opus", "sonnet"], backend="claude-cli", lang="en")


# @S-run-workspace-001
def test_new_run_folder_and_pending_state(tmp_path):
    run = mk(tmp_path, "My Article!")
    assert run.root.name == "20261022-0930-my-article"
    st = run.state()
    assert [st["phases"][p]["status"] for p in PHASES] == ["pending"] * len(PHASES)
    assert st["models"] == ["opus", "sonnet"] and st["backend"] == "claude-cli"


def test_same_minute_same_slug_gets_suffix(tmp_path):
    a, b = mk(tmp_path), mk(tmp_path)
    assert a.root != b.root and b.root.name.endswith("-2")


def _done_through(run, last):
    for ph in PHASES[: PHASES.index(last) + 1]:
        run.mark(ph, "done")


# @S-run-workspace-002
def test_done_phase_with_same_inputs_is_skipped(tmp_path):
    run = mk(tmp_path)
    run.path("00-intake.json").write_text("{}")
    run.path("01-sources").mkdir()
    run.path("01-sources/manifest.json").write_text("[]")
    _done_through(run, "rubric")
    assert run.needs_run("rubric") is False


# @S-run-workspace-003
def test_changed_input_marks_downstream_stale(tmp_path):
    run = mk(tmp_path)
    run.path("00-intake.json").write_text("{}")
    (run.path("01-sources/normalized")).mkdir(parents=True)
    run.path("01-sources/manifest.json").write_text("[]")
    run.path("01-sources/segments.json").write_text("{}")
    run.path("02-rubric.json").write_text("{}")
    _done_through(run, "review")
    run.path("01-sources/manifest.json").write_text('[{"changed": 1}]')
    newly = run.refresh()
    assert run.status("sources") == "done"
    assert run.status("rubric") == "stale" and run.status("review") == "stale"
    assert newly[:2] == ["rubric", "review"]


# @S-run-workspace-004
def test_rerun_from_marks_later_phases_stale(tmp_path):
    run = mk(tmp_path)
    _done_through(run, "report")
    run.rerun_from("review")
    st = run.state()["phases"]
    assert st["rubric"]["status"] == "done"
    for ph in ("review", "factcheck", "debate", "consensus", "report"):
        assert st[ph]["status"] == "stale"
    assert st["revision"]["status"] == "pending"


# @S-run-workspace-005
def test_unfinished_runs_listed(tmp_path):
    finished = mk(tmp_path, "a")
    for ph in PHASES:
        finished.mark(ph, "done")
    half = mk(tmp_path, "b")
    _done_through(half, "rubric")
    got = [r.root for r in unfinished_runs(tmp_path / "runs")]
    assert got == [half.root]


# @S-run-workspace-006
def test_raw_source_is_write_once(tmp_path):
    run = mk(tmp_path)
    p = run.write_raw_source("u1.html", b"original")
    with pytest.raises(FileExistsError):
        run.write_raw_source("u1.html", b"changed")
    assert p.read_bytes() == b"original"
    assert not [f for f in p.parent.iterdir() if f.name.endswith(".tmp")]


# @N-run-workspace-001
def test_resume_settings_come_from_state_not_current_config(tmp_path):
    from ant_peer_review.store import Config, Store
    run = mk(tmp_path)
    store = Store(tmp_path / "home")
    store.save_config(Config(models=["opus", "fable"], backend="claude-cli"))
    models, backend, lang = Run(run.root).settings()
    assert models == ["opus", "sonnet"] and backend == "claude-cli" and lang == "en"


# @S-run-workspace-007
def test_every_call_cost_and_phase_time_recorded(tmp_path):
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    import ant_peer_review.cli as cli
    from ant_peer_review.backends.base import Result
    from ant_peer_review.decision import run_decision
    from ant_peer_review.jsonio import read_jsonl
    from ant_peer_review.pipeline import Ctx, run_pipeline
    from ant_peer_review.store import Config, Store
    from ant_peer_review.ui import ScriptedIO
    from helpers import ScriptBackend, make_run, review_data

    def paid(data, usd):
        return lambda p: Result(model="", model_id="", data=data, cost_usd=usd)
    run = make_run(tmp_path)
    for ph in ("intake", "sources", "rubric"):
        run.mark(ph, "done")
    b = ScriptBackend({("*", "review"): paid(review_data(claims=[{}]), 1.25),
                       ("*", "factcheck"): paid({"status": "cannot_verify", "reason": "no_source",
                                                 "sources": []}, 0.5),
                       ("*", "debate"): {"responses": []},
                       ("*", "revise_a"): {"paragraphs": [], "corrections": []},
                       ("*", "revise_b"): {"headline_options": [], "paragraphs": [], "notes": ""},
                       ("*", "rereview"): {"verdicts": []}})
    store = Store(tmp_path / "home")
    ctx = Ctx(io=ScriptedIO([]), store=store, cfg=Config(), backend=b, models=["opus", "sonnet"],
              lang="en", interactive=False)
    run_pipeline(run, ctx)
    lines = read_jsonl(run.path("costs.jsonl"))
    assert {"phase", "task", "model", "cost_usd"} <= set(lines[0])
    assert sum(x["cost_usd"] for x in lines if x["task"] == "review") == 2.5
    assert any(x["phase"] == "factcheck" and x["cost_usd"] == 0.5 for x in lines)
    assert any(x["cost_usd"] is None for x in lines)                  # debate reports no cost
    st = run.state()["phases"]
    assert all("seconds" in st[ph] for ph in ("review", "factcheck", "debate", "report"))
    row = cli.summary_row(run)
    fc = [x for x in lines if x["task"] == "factcheck"]
    assert fc and all(x["cost_usd"] == 0.5 for x in fc)
    assert row["cost_usd"] == 2.5 + 0.5 * len(fc) and isinstance(row["minutes"], float)

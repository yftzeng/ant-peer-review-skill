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

"""S-intake-016: a source under review or embargoed is held back before any model reads it."""
from test_cli import TEXT, CountingFake, NoAskIO, env  # noqa: F401  (env is a fixture)

from ant_peer_review import cli
from ant_peer_review.jsonio import read_json
from ant_peer_review.ui import ScriptedIO
from ant_peer_review.workspace import list_runs
from ant_peer_review.store import Config


def _new(store, *extra, io=None):
    io = io or NoAskIO()
    return cli.main(["new", "--yes", "--backend", "fake", "--target", TEXT, *extra],
                    io=io, store=store), io


# @S-intake-016
def test_status_asked_before_any_model_and_no_ends_without_a_run(env):
    env.save_config(Config())
    io = ScriptedIO(["1", "A manuscript we were sent.", "/done", "3", ""])   # under review; allowed? no
    cli.main([], io=io, store=env)
    assert "confidential" in io.text and "outside AI" in io.text
    assert CountingFake.calls == [] and list_runs(env.runs_dir) == []


# @S-intake-016
def test_share_of_an_embargoed_source_is_refused(env):
    env.save_config(Config())
    io = ScriptedIO(["3", "An embargoed press release.", "/done", "4"])
    cli.main([], io=io, store=env)
    assert "not public yet" in io.text
    assert CountingFake.calls == [] and list_runs(env.runs_dir) == []


# @S-intake-016
def test_status_from_arguments(env):
    code, _ = _new(env)
    assert read_json(list_runs(env.runs_dir)[-1].path("00-intake.json"))["source_status"] == "public"
    for extra, word in ((["--source-status", "under_review"], "--confidential-ok"),
                        (["--source-status", "secret"], "under_review"),
                        (["--source-status", ""], "under_review"),
                        (["--purpose", "share", "--source-status", "embargoed", "--confidential-ok"],
                         "not public yet")):
        before = len(list_runs(env.runs_dir))
        code, io = _new(env, *extra)
        assert code == cli.EXIT_USAGE and word in io.text, extra
        assert len(list_runs(env.runs_dir)) == before
    code, _ = _new(env, "--source-status", "under_review", "--confidential-ok")
    run = list_runs(env.runs_dir)[-1]
    assert read_json(run.path("00-intake.json"))["source_status"] == "under_review"
    assert read_json(run.path("00-intake.json"))["source_permission"] is True
    from ant_peer_review.i18n import T
    from ant_peer_review.report import status_line
    assert "until it is public" in status_line(T("en"), "under_review")
    assert "公開前" in status_line(T("zh-TW"), "embargoed") and "公开前" in status_line(T("zh-CN"), "embargoed")
    assert "until" not in status_line(T("en"), "preprint")
    assert status_line(T("en"), None) == ""
    assert "<b>" not in status_line(T("en"), "<b>x")


# @S-intake-016
def test_the_older_intake_path_asks_too():
    from ant_peer_review.i18n import T
    from ant_peer_review.intake import run_intake_interactive
    t = T("en")
    assert run_intake_interactive(ScriptedIO(["1", "Manuscript.", "/done", "3", ""]), t, "en") is None
    assert run_intake_interactive(ScriptedIO(["3", "Embargoed.", "/done", "4"]), t, "en") is None
    got = run_intake_interactive(ScriptedIO(["1", "Manuscript.", "/done", "3", "2", "", "", "", "", "",
                                             "", "", ""]), t, "en")
    assert got["source_status"] == "under_review"
    assert "source_status" not in run_intake_interactive(
        ScriptedIO(["2", "My notes.", "/done", "", "", "", "", "", "", "", ""]), t, "en")


# @S-intake-016
def test_allowed_confidential_source_is_kept_and_older_path_stops(env, tmp_path):
    env.save_config(Config())
    io = ScriptedIO(["1", "A manuscript we were sent.", "/done", "3", "2"] + [""] * 40)
    try:
        cli.main([], io=io, store=env)
    except EOFError:
        pass
    runs = list_runs(env.runs_dir)
    assert runs and read_json(runs[0].path("00-intake.json"))["source_status"] == "under_review"
    import pytest
    from ant_peer_review import pipeline
    from ant_peer_review.workspace import create_run
    run = create_run(tmp_path / "runs", "x", models=["opus"], backend="fake", lang="en")
    ctx = pipeline.Ctx(io=ScriptedIO(["1", "Manuscript.", "/done", "3", ""]), store=env, cfg=Config(),
                       backend=None, models=["opus"], lang="en", interactive=True)
    with pytest.raises(pipeline.Stop, match="no run"):
        pipeline.ph_intake(run, ctx)
    assert not run.path("00-intake.json").exists()


# @S-intake-016
def test_targets_on_the_command_line_without_yes_still_ask(env):
    env.save_config(Config())
    io = ScriptedIO(["3", ""])          # under review; allowed? no
    code = cli.main(["new", "--backend", "fake", "--target", TEXT], io=io, store=env)
    assert code == cli.EXIT_USAGE and "outside AI" in io.text
    assert CountingFake.calls == [] and list_runs(env.runs_dir) == []

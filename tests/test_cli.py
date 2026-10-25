import pytest

import ant_peer_review.cli as cli
from ant_peer_review.backends.base import BackendError
from ant_peer_review.backends.fake import FakeBackend
from ant_peer_review.jsonio import read_json
from ant_peer_review.store import Store
from ant_peer_review.ui import ScriptedIO
from ant_peer_review.workspace import PHASES, list_runs

TEXT = "# Post\n\nOur product is great. It grew 40% last year.\n\nBuy now."


class CountingFake(FakeBackend):
    calls = []

    def run(self, model, *, task, **kw):
        CountingFake.calls.append((model, task))
        return super().run(model, task=task, **kw)


class NoAskIO(ScriptedIO):
    def ask(self, prompt):
        raise AssertionError(f"prompted in non-interactive mode: {prompt}")


class OfflineCrawler:
    """Tests never reach the network: every URL fails like an unreachable host."""

    def fetch(self, url):
        from ant_peer_review.sources.crawler import FetchError
        raise FetchError("offline", url)


@pytest.fixture
def env(tmp_path, monkeypatch):
    CountingFake.calls = []
    monkeypatch.setattr(cli, "get_backend", lambda name: CountingFake())
    monkeypatch.setattr(cli, "make_feed_crawler", lambda store: OfflineCrawler())
    return Store(tmp_path / "home")


def new_run(store, io=None):
    io = io or NoAskIO()
    code = cli.main(["new", "--yes", "--backend", "fake", "--target", TEXT], io=io, store=store)
    return code, io, list_runs(store.runs_dir)[-1]


# @S-cli-001
# @N-cli-001
def test_non_interactive_to_decision_gate(env):
    code, io, run = new_run(env)
    assert code == 3
    assert run.path("06-report.v1.md").exists() and run.path("07-revision/A.md").exists()
    assert run.status("decision") == "pending"
    assert "Peer reviewers: opus, sonnet" in io.text
    assert f"ant-peer-review decide {run.id}" in io.text


# @S-cli-002
def test_decide_then_resume(env):
    _, _, run = new_run(env)
    CountingFake.calls = []
    assert cli.main(["decide", run.id, "--yes", "--choice", "A"], io=NoAskIO(), store=env) == 0
    assert cli.main(["resume", run.id, "--yes"], io=NoAskIO(), store=env) == 0
    assert run.path("audit.md").read_text() == run.path("07-revision/A.md").read_text()
    assert all(run.status(p) == "done" for p in PHASES)
    assert sorted(task for _, task in CountingFake.calls) == ["reply", "summary"]


# @S-cli-003
def test_rerun_from_review(env):
    _, _, run = new_run(env)
    cli.main(["decide", run.id, "--yes", "--choice", "A"], io=NoAskIO(), store=env)
    CountingFake.calls = []
    cli.main(["rerun", run.id, "--from", "review", "--yes"], io=NoAskIO(), store=env)
    assert {m for m, t in CountingFake.calls if t == "review"} == {"opus", "sonnet"}
    assert run.path("06-report.v2.md").exists()


# @S-cli-004
def test_unfinished_run_offered(env):
    _, _, run = new_run(env)
    io = ScriptedIO([])
    cli.main([], io=io, store=env)
    assert f"Continue {run.id} from phase decision" in io.text


# @S-cli-005
def test_ctrl_c_leaves_resumable(env, monkeypatch):
    class Boom(CountingFake):
        def run(self, model, *, task, **kw):
            if task == "review":
                raise KeyboardInterrupt
            return super().run(model, task=task, **kw)
    monkeypatch.setattr(cli, "get_backend", lambda name: Boom())
    io = NoAskIO()
    code = cli.main(["new", "--yes", "--target", TEXT], io=io, store=env)
    run = list_runs(env.runs_dir)[-1]
    assert code == 130 and run.status("review") == "pending"
    assert f"ant-peer-review resume {run.id}" in io.text


# @S-cli-006
def test_backend_failure_pauses(env, monkeypatch):
    class Down(CountingFake):
        def run(self, model, *, task, **kw):
            raise BackendError("down", reason="offline")
    monkeypatch.setattr(cli, "get_backend", lambda name: Down())
    code = cli.main(["new", "--yes", "--target", TEXT], io=NoAskIO(), store=env)
    run = list_runs(env.runs_dir)[-1]
    assert code == 3
    assert run.status("sources") == "done" and run.status("rubric") == "done"
    assert run.status("review") == "pending"
    assert read_json(run.path("03-reviews/opus.json"))["reason"] == "offline"


# @S-cli-007
def test_runs_lists_next_phase(env):
    _, _, run = new_run(env)
    io = NoAskIO()
    cli.main(["runs", "--yes"], io=io, store=env)
    assert f"{run.id}" in io.text and "next: decision" in io.text


def test_models_override_recorded_in_run(env):
    cli.main(["new", "--yes", "--models", "opus,fable", "--target", TEXT], io=NoAskIO(), store=env)
    run = list_runs(env.runs_dir)[-1]
    assert run.settings()[0] == ["opus", "fable"]
    assert env.load_config().models == ["opus", "sonnet"]


# @S-cli-008
def test_slug_from_target(env):
    from ant_peer_review.cli import slug_for
    from ant_peer_review.workspace import slugify
    assert slugify(slug_for("/tmp/x/my-article.md")) == "my-article"
    assert slugify(slug_for("https://example.com/blog/hello-world")) == "example-com-hello-world"
    assert slugify(slug_for("# Big News\nBody")) == "big-news"


# @S-cli-009
def test_abandoned_intake_leaves_no_run(env):
    env.save_config(__import__("ant_peer_review.store", fromlist=["Config"]).Config())
    io = ScriptedIO(["1", "https://example.com/a", "/done", "4"])  # input ends in layer a
    code = cli.main([], io=io, store=env)
    assert code == 130
    assert list_runs(env.runs_dir) == []


# @S-cli-010
def test_delete_unfinished_run_from_menu(env):
    from ant_peer_review.workspace import create_run
    run = create_run(env.runs_dir, "run", models=["opus", "sonnet"], backend="fake", lang="en")
    env.save_config(__import__("ant_peer_review.store", fromlist=["Config"]).Config())
    # menu: 1) continue run  2) delete an unfinished run  3) new ; then pick run 1, decline
    io = ScriptedIO(["2", "1", "n"])
    cli.main([], io=io, store=env)
    assert run.root.exists() and "1 file" in io.text
    io = ScriptedIO(["2", "1", "y"])
    cli.main([], io=io, store=env)
    assert not run.root.exists()


# @S-cli-013
def test_runs_summary(env, tmp_path):
    import csv
    from ant_peer_review.jsonio import write_json
    from ant_peer_review.workspace import create_run
    for slug, total, grade, red in (("first", 74.3, "good", {}), ("second", 61.0, "fail",
                                                                   {"illegal": "confirmed"})):
        r = create_run(env.runs_dir, slug, models=["opus", "sonnet"], backend="fake", lang="en")
        write_json(r.path("00-intake.json"), {"purpose": "audit", "targets": [
            {"kind": "text", "value": f"# {slug.title()} Post\n\nbody"}], "audience": {}})
        write_json(r.path("06-report.v1.json"), {"version": 1, "total": total, "grade": grade,
                                                 "red_lines": dict({"hallucination": "clear"}, **red)})
        write_json(r.path("05-consensus.json"), {"findings": [{}, {}, {}]})
    create_run(env.runs_dir, "empty", models=["opus", "sonnet"], backend="fake", lang="en")
    io = NoAskIO()
    cli.main(["runs", "--yes", "--summary"], io=io, store=env)
    rows = [ln for ln in io.text.splitlines() if ln.startswith("| 2026") or ln.startswith("| 20")]
    assert len(rows) == 3
    first = [ln for ln in rows if "First Post" in ln][0]
    assert "74.3" in first and "good" in first and "| 3 |" in first
    assert "illegal" in [ln for ln in rows if "Second Post" in ln][0]
    out = tmp_path / "summary.csv"
    cli.main(["runs", "--yes", "--summary", "--format", "csv", "--out", str(out)], io=NoAskIO(),
             store=env)
    data = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(data) == 3 and {"run", "title", "total", "grade", "red_lines", "findings",
                               "next"} <= set(data[0])


# @S-cli-020
def test_deliver_rewrites_outputs(env):
    _, _, run = new_run(env)
    cli.main(["decide", run.id, "--yes", "--choice", "A", "--reply", "none"], io=NoAskIO(), store=env)
    assert not run.path("reply-critical.md").exists()
    run.path("review.md").unlink()
    before = run.path("audit.md").read_text()
    assert cli.main(["deliver", run.id, "--reply", "critical"], io=NoAskIO(), store=env) == 0
    assert run.path("review.md").exists() and run.path("reply-critical.md").exists()
    assert not run.path("reply-socratic.md").exists()
    assert run.path("audit.md").read_text() == before


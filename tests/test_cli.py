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


@pytest.fixture
def env(tmp_path, monkeypatch):
    CountingFake.calls = []
    monkeypatch.setattr(cli, "get_backend", lambda name: CountingFake())
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
    assert run.path("final.md").read_text() == run.path("07-revision/A.md").read_text()
    assert all(run.status(p) == "done" for p in PHASES)
    assert CountingFake.calls == []


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

import pytest

from ant_peer_review.backends.base import Backend, BackendError, Result
from ant_peer_review.store import Store


class ProbeBackend(Backend):
    """Answers probes; models in `down` fail."""
    name = "probe"

    def __init__(self, down=()):
        self.down = set(down)

    def run(self, model, *, task, system, prompt, schema, tools=(), effort="high", timeout=900):
        if model in self.down:
            raise BackendError("model not available on this plan")
        return Result(model=model, model_id=model, data={"ok": True})


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "home")

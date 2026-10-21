"""Backend A: Anthropic SDK. Reserved interface; build order puts it second (D-2).

It fails loudly instead of pretending: choose `claude-cli` until it lands.
"""
from __future__ import annotations

from .base import Backend, BackendError, Result


class AnthropicApiBackend(Backend):
    name = "anthropic-api"

    def run(self, model, *, task, system, prompt, schema, tools=(), effort="high",
            timeout=900) -> Result:
        raise BackendError(
            "the anthropic-api backend is not implemented yet; "
            "run `ant-peer-review config backend` and choose claude-cli",
            reason="error")

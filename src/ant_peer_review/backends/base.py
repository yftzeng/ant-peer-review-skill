"""Backend interface: one structured call to one model.

Vendor-neutral on purpose (D-3): nothing here assumes Anthropic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

MODEL_IDS = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "fable": "claude-fable-5-1",
}


class BackendError(RuntimeError):
    """The call failed (transport, timeout, invalid output after retries)."""

    def __init__(self, message: str, *, reason: str = "error"):
        super().__init__(message)
        self.reason = reason  # error | timeout | offline | invalid_output


@dataclass
class Result:
    model: str                       # alias, e.g. "opus"
    model_id: str                    # resolved id actually requested
    data: dict | None                # schema-valid structured output (None if refused)
    refused: bool = False
    refusal_detail: str = ""
    cost_usd: float | None = None
    tool_calls: list[dict] = field(default_factory=list)    # [{"name", "input"}]
    tool_results: list[str] = field(default_factory=list)   # raw text of tool results
    raw: Any = None


class Backend(ABC):
    name: str = "base"

    @abstractmethod
    def run(self, model: str, *, task: str, system: str, prompt: str,
            schema: dict, tools: tuple[str, ...] = (), effort: str = "high",
            timeout: int = 900) -> Result:
        """Run one call. `task` names the step (review, debate, ...) for logs/fakes."""

    def probe(self, model: str) -> str | None:
        """Return None if the model answers, else a short reason."""
        try:
            r = self.run(model, task="probe", system="Reply with ok=true.",
                         prompt="Return ok=true.",
                         schema={"type": "object", "properties": {"ok": {"type": "boolean"}},
                                 "required": ["ok"], "additionalProperties": False},
                         effort="low", timeout=180)
        except BackendError as e:
            return str(e)
        if r.refused or not r.data:
            return r.refusal_detail or "no answer"
        return None


def get_backend(name: str) -> Backend:
    if name == "claude-cli":
        from .claude_cli import ClaudeCliBackend
        return ClaudeCliBackend()
    if name == "anthropic-api":
        from .anthropic_api import AnthropicApiBackend
        return AnthropicApiBackend()
    if name == "fake":
        from .fake import FakeBackend
        return FakeBackend()
    raise ValueError(f"unknown backend: {name}")

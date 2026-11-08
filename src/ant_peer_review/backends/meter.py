"""S-run-workspace-007: every model call's cost, appended to the run's costs.jsonl.

Wraps any backend; the phase is set by whoever drives the run (the pipeline, decide,
deliver, factcheck). A backend that reports no cost is recorded as null, not 0."""
from __future__ import annotations

import threading
import time
from datetime import datetime

from ..jsonio import append_jsonl
from .base import Backend, Result

_LOCK = threading.Lock()


class Meter(Backend):
    def __init__(self, inner: Backend, run, phase: str = ""):
        self.inner = inner.inner if isinstance(inner, Meter) else inner
        self.run_ = run
        self.phase = phase
        self.name = self.inner.name

    def __getattr__(self, attr):          # anything else a backend offers
        return getattr(self.inner, attr)

    def run(self, model: str, **kw) -> Result:
        t0 = time.monotonic()
        res, err = None, ""
        try:
            res = self.inner.run(model, **kw)
            return res
        except Exception as e:  # noqa: BLE001 - recorded, then raised again
            err = type(e).__name__
            raise
        finally:
            line = {"at": datetime.now().isoformat(timespec="seconds"), "phase": self.phase,
                    "task": kw.get("task", ""), "model": model,
                    "cost_usd": getattr(res, "cost_usd", None),
                    "seconds": round(time.monotonic() - t0, 1)}
            if err:
                line["error"] = err
            with _LOCK:
                append_jsonl(self.run_.path("costs.jsonl"), line)

"""Scriptable backend and canned reviewer outputs for pipeline tests."""
import json

from ant_peer_review.backends.base import Backend, BackendError, Result
from ant_peer_review.jsonio import write_json
from ant_peer_review.workspace import create_run

DIMS = ["macro", "accuracy", "micro", "impact"]
RED = ["illegal", "hallucination", "pr_landmine", "plagiarism", "sensitive_politics",
       "human_rights"]


def review_data(scores=(80, 70, 90, 60), issues=(), claims=(), flags=(), stage="growth"):
    return {
        "orientation": "A short piece about X.",
        "scores": [{"dimension": d, "score": s, "rationale": "r", "anchors": ["D1.P01.S1"]}
                   for d, s in zip(DIMS, scores)],
        "issues": [dict({"id": "I1", "anchor": "D1.P01.S1", "level": "macro",
                         "dimension": "macro", "observation": "obs", "standard": "std",
                         "why_it_matters": "why", "action": "act", "severity": "major",
                         "claim_ids": []}, **i) for i in issues],
        "claims": [dict({"id": "K1", "anchor": "D1.P02.S1", "text": "Revenue grew 40% in 2025",
                         "type": "number"}, **c) for c in claims],
        "sensitivity": [],
        "red_lines": [{"key": k, "flag": k in flags, "severity": "high" if k in flags else "none",
                       "anchors": [], "comment": "c" if k in flags else ""} for k in RED],
        "s_curve": {"stage": stage, "evidence_query": "q", "fit_note": "n"},
    }


def ok(model, data):
    return {"model": model, "model_id": f"claude-{model}", "status": "ok", "data": data,
            "backend": "test"}


class ScriptBackend(Backend):
    """handlers: {(model, task): fn(prompt) -> Result | dict | Exception}."""
    name = "script"

    def __init__(self, handlers=None, default=None):
        self.handlers = handlers or {}
        self.default = default
        self.calls = []

    def run(self, model, *, task, system, prompt, schema, tools=(), effort="high", timeout=900):
        self.calls.append({"model": model, "task": task, "prompt": prompt, "system": system,
                           "tools": tools})
        h = self.handlers.get((model, task)) or self.handlers.get(("*", task)) or self.default
        out = h(prompt) if callable(h) else h
        if isinstance(out, Exception):
            raise out
        if isinstance(out, Result):
            out.model, out.model_id = model, f"claude-{model}"
            return out
        return Result(model=model, model_id=f"claude-{model}", data=out)


def make_run(tmp_path, text="# Title\n\nFirst para.\n\nRevenue grew 40% in 2025. Second.",
             models=("opus", "sonnet")):
    run = create_run(tmp_path / "runs", "t", models=list(models), backend="script", lang="en")
    write_json(run.path("00-intake.json"), {"purpose": "audit",
                                            "targets": [{"kind": "text", "value": text}],
                                            "audience": {"expertise": "expert", "role": None,
                                                         "lens": None, "trust": None,
                                                         "purpose": "trend"}, "lang": "en"})
    from ant_peer_review.rubric import propose
    from ant_peer_review.sources.acquire import run_sources
    run_sources(run, crawler=None)
    rub = propose({k: None for k in ["expertise", "role", "lens", "trust", "purpose"]})
    write_json(run.path("02-rubric.json"), rub)
    return run

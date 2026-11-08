"""Deterministic offline backend: `--backend fake` for demos and smoke tests.

It never calls a model. Outputs are schema-valid and anchored to ids found in
the prompt, so the whole pipeline can be exercised without network or cost.
"""
from __future__ import annotations

import re

from ..schemas import RED_LINES
from .base import MODEL_IDS, Backend, Result


def _ids(prompt: str) -> list[str]:
    return re.findall(r"\[(D[\w-]+\.P\d+(?:\.S\d+)?)\]", prompt)


def _para_ids(prompt: str) -> list[str]:
    seen = []
    for i in _ids(prompt):
        p = ".".join(i.split(".")[:2])
        if p not in seen:
            seen.append(p)
    return seen


class FakeBackend(Backend):
    name = "fake"

    def run(self, model, *, task, system, prompt, schema, tools=(), effort="high",
            timeout=900) -> Result:
        ids = _ids(prompt) or ["D1.P01"]
        paras = _para_ids(prompt) or ["D1.P01"]
        bias = {"opus": 0, "sonnet": 4, "fable": -3}.get(model, 0)
        data = getattr(self, f"_{task}")(model, ids, paras, bias, prompt)
        calls, results = [], []
        if task == "factcheck":
            calls = [{"name": "WebSearch", "input": {"query": "fake"}}]
            results = ["Links: https://example.org/fake-source"]
        return Result(model=model, model_id=MODEL_IDS.get(model, model), data=data,
                      cost_usd=0.0, tool_calls=calls, tool_results=results)

    def _probe(self, *a):
        return {"ok": True}

    def _summary(self, model, ids, paras, bias, prompt):
        found = re.findall(r'"id": "(F\d+)"', prompt)
        return {"summary": f"[fake:{model}] {len(found)} findings.",
                "key_points": [{"text": "Fix the first finding.", "findings": found[:1]}] if found
                else []}

    def _reply(self, model, ids, paras, bias, prompt):
        styles = re.findall(r"^- (\w+): about \d+ units", prompt, re.M)
        return {"replies": [{"style": s, "text": f"[fake:{model}] {s} reply."} for s in styles]}

    def _voice(self, model, ids, paras, bias, prompt):
        n = len(re.findall(r"^Post \d+:", prompt, re.M))
        return {"description": f"[fake:{model}] short, direct posts.", "openers": [],
                "closers": [], "emoji": "rare", "hashtags": "none",
                "style_counts": {"summary": 0, "insight": n, "question": 0, "addon": 0, "pick": 0}}

    def _share(self, model, ids, paras, bias, prompt):
        keys = re.findall(r"^- key (\S+):", prompt, re.M)
        url = (re.findall(r'"url": "([^"]*)"', prompt) or [""])[0]
        return {"posts": [{"key": k, "text": f"[fake:{model}] {k} {url}".strip()} for k in keys]}

    def _share_analysis(self, model, ids, paras, bias, prompt):
        return {"purpose": f"[fake:{model}] purpose", "claims": [], "direction": "middle",
                "why": "fake", "thesis": f"[fake:{model}] thesis", "anchors": ["fake anchor"],
                "subject": {"topic": "", "terms": []}, "origin": []}

    def _readers_mix(self, model, ids, paras, bias, prompt):
        return {"weights": {"public": 25, "beginner": 30, "expert": 30, "business": 15},
                "why": {p: f"[fake:{model}] {p}" for p in ("public", "beginner", "expert", "business")},
                "basis": {"stage": "fake", "maturity": "fake", "media": "fake"}}

    def _reader(self, model, ids, paras, bias, prompt):
        return {"reports": [{"key": k, "verdict": "met", "hook": "", "peak": "", "stuck": "",
                             "takeaway": f"[fake:{model}]", "would": "", "would_not": "",
                             "reason": "fake"} for k in re.findall(r"^Post (\S+):$", prompt, re.M)]}

    def _reader_revise(self, model, ids, paras, bias, prompt):
        return {"posts": []}

    def _share_rewrite(self, model, ids, paras, bias, prompt):
        return {"posts": []}         # keep the texts; the gate marks what still fails

    def _judge(self, *a):
        return {"verdicts": []}       # every fake text passes

    def _rewrite(self, model, ids, paras, bias, prompt):
        return self._reply(model, ids, paras, bias, prompt)

    def _profile(self, model, ids, paras, bias, prompt):
        # Suggests nothing for the audience, so the layers are asked as without analysis.
        return {"genre": "other", "topic": "", "brand": "", "notes": "",
                "identity": {k: "" for k in ("title", "author", "organization", "email", "date")},
                "audience": {k: [] for k in ("expertise", "role", "lens", "trust", "purpose")},
                "fact_sources": []}

    def _review(self, model, ids, paras, bias, prompt):
        keys = re.findall(r"^- (\S+) \(weight \d+\)", prompt, re.M) or \
            ["macro", "accuracy", "micro", "impact"]
        first, last = ids[0], ids[-1]
        return {
            "orientation": f"[fake:{model}] The piece has {len(paras)} paragraphs.",
            "scores": [{"dimension": k, "score": float(70 + bias + 3 * n), "rationale": "fake",
                        "anchors": [first]} for n, k in enumerate(keys)],
            "issues": [
                {"id": "I1", "anchor": last, "level": "macro", "dimension": keys[0],
                 "observation": "The conclusion does not return to the opening claim.",
                 "standard": "Conclusion supports the opening", "why_it_matters": "Weak close",
                 "action": "Restate the thesis in the last paragraph.", "severity": "major",
                 "claim_ids": []},
                {"id": "I2", "anchor": first, "level": "micro", "dimension": keys[-1],
                 "observation": f"[{model}] Wordy sentence.", "standard": "Concision",
                 "why_it_matters": "Readability", "action": "Cut filler words.",
                 "severity": "minor", "claim_ids": []},
            ],
            "claims": [{"id": "K1", "anchor": first, "text": "The first sentence states a fact.",
                        "type": "other"}],
            "sensitivity": [],
            "red_lines": [{"key": k, "flag": False, "severity": "none", "anchors": [],
                           "comment": ""} for k in RED_LINES],
            "s_curve": {"stage": "growth", "evidence_query": "topic adoption", "fit_note": "ok"},
        }

    def _review_reduce(self, model, ids, paras, bias, prompt):
        return {"orientation": f"[fake:{model}] The whole piece, from its parts.",
                "macro": {"score": float(70 + bias), "rationale": "fake"}, "issues": []}

    def _factcheck(self, *a):
        return {"status": "supported", "reason": "fake",
                "sources": [{"url": "https://example.org/fake-source",
                             "supporting_excerpt": "fake excerpt", "kind": "independent"}]}

    def _debate(self, model, ids, paras, bias, prompt):
        targets = re.findall(r'"target": "([^"]+)"', prompt)
        out = []
        for t in targets:
            if t.endswith(":I1"):
                out.append({"target": t, "position": "support", "evidence": "same",
                            "duplicate_of": "I1"})
        return {"responses": out}

    def _revise_a(self, model, ids, paras, bias, prompt):
        return {"paragraphs": [], "corrections": []}

    def _revise_b(self, model, ids, paras, bias, prompt):
        return {"headline_options": ["A sharper headline"],
                "paragraphs": [{"id": paras[-1], "text": "[fake rewrite] Closing that restates "
                                "the thesis.", "addresses": ["F01"]}], "notes": "fake"}

    def _rereview(self, model, ids, paras, bias, prompt):
        found = sorted(set(re.findall(r'"id": "(F\d+)"', prompt)))
        return {"verdicts": [{"issue": f, "verdict": "RESOLVED", "note": "fake"} for f in found]}

    def _recheck(self, model, ids, paras, bias, prompt):
        found = sorted(set(re.findall(r'"id": "(F\d+)"', prompt)))
        return {"verdicts": [{"finding": f, "verdict": "IMPROVED" if i else "RESOLVED",
                              "evidence": ids[0], "note": "fake"} for i, f in enumerate(found)]}

    def _recheck_claims(self, model, ids, paras, bias, prompt):
        found = sorted(set(re.findall(r'"id": "(F\d+)"', prompt)))
        return {"claims": [{"finding": f, "author_claim": "fixed"} for f in found]}

    def _draft(self, model, ids, paras, bias, prompt):
        return {"title": "Fake draft", "paragraphs": [
            "This draft was produced offline by the fake backend.",
            "It summarizes the materials in two short paragraphs."]}

"""Fact-check ledger: build, check with search provenance, continue, finalize."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime

from . import prompts
from .backends.base import Backend, BackendError
from .jsonio import read_json, write_text_atomic
from .schemas import FACTCHECK
from .workspace import Run

LEDGER = "factcheck/ledger.jsonl"
RETRYABLE = {"offline", "timeout", "error", "no_search"}
SEARCH_TOOLS = ("WebSearch", "WebFetch")


def read_ledger(run: Run) -> list[dict]:
    p = run.path(LEDGER)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_ledger(run: Run, ledger: list[dict]) -> None:
    text = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in ledger)
    write_text_atomic(run.path(LEDGER), text)


def snapshot(ledger: list[dict]) -> str:
    pairs = sorted((c["id"], c["status"], c.get("reason", "")) for c in ledger)
    return hashlib.sha256(json.dumps(pairs).encode()).hexdigest()[:16]


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[\W_]+", "", t)


def is_retryable(c: dict) -> bool:
    return c["status"] == "pending" or (c["status"] == "cannot_verify"
                                        and c.get("reason") in RETRYABLE)


def build_ledger(reviews: dict[str, dict], existing: list[dict], models: list[str]) -> list[dict]:
    ledger = [dict(c) for c in existing]
    by_key = {(c["anchor"], _norm(c["text"])): c for c in ledger if c["type"] != "s_curve_stage"}
    n = sum(1 for c in ledger if c["id"].startswith("C"))
    for m in models:
        rec = reviews.get(m, {})
        if rec.get("status") != "ok":
            continue
        for k in rec["data"].get("claims", []):
            key = (k["anchor"], _norm(k["text"]))
            ref = f"{m}:{k['id']}"
            if key in by_key:
                c = by_key[key]
                if ref not in c["refs"]:
                    c["refs"].append(ref)
                if m not in c["extracted_by"]:
                    c["extracted_by"].append(m)
                continue
            n += 1
            c = {"id": f"C{n:02d}", "anchor": k["anchor"], "text": k["text"], "type": k["type"],
                 "status": "pending", "reason": "", "sources": [], "extracted_by": [m],
                 "refs": [ref], "checked_by": "", "updated_at": ""}
            ledger.append(c)
            by_key[key] = c
    if not any(c["id"] == "SC1" for c in ledger):
        stages = []
        queries = {}
        for m in models:
            rec = reviews.get(m, {})
            if rec.get("status") == "ok":
                sc = rec["data"].get("s_curve", {})
                if sc.get("stage") and sc["stage"] != "unknown":
                    stages.append(sc["stage"])
                    queries.setdefault(sc["stage"], sc.get("evidence_query", ""))
        if stages:
            counts = Counter(stages)
            top = max(counts.values())
            stage = next(s for s in stages if counts[s] == top)
            ledger.append({"id": "SC1", "anchor": "D1", "type": "s_curve_stage", "stage": stage,
                           "text": f"The topic of this piece is at the '{stage}' stage of its "
                                   f"adoption S-curve. Suggested evidence search: {queries[stage]}",
                           "status": "pending", "reason": "", "sources": [],
                           "extracted_by": sorted(set(m for m in models
                                                      if reviews.get(m, {}).get("status") == "ok")),
                           "refs": [], "checked_by": "", "updated_at": ""})
    return ledger


def context_for(run: Run, anchor: str) -> str:
    segs = read_json(run.path("01-sources/segments.json"), default={})
    pid = ".".join(anchor.split(".")[:2])
    for doc in segs.values():
        for s in doc:
            if s["id"] == pid:
                return s["text"]
    return ""


def _provenance_filter(sources: list[dict], tool_text: str) -> list[dict]:
    kept = []
    for s in sources:
        url = (s.get("url") or "").strip()
        if url and url.rstrip("/") in tool_text:
            kept.append(s)
    return kept


def check_claim(backend: Backend, model: str, claim: dict, context: str, lang: str) -> dict:
    c = dict(claim)
    c["checked_by"] = model
    c["updated_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        res = backend.run(model, task="factcheck", system=prompts.factcheck_system(lang),
                          prompt=prompts.factcheck_prompt(claim, context), schema=FACTCHECK,
                          tools=SEARCH_TOOLS, effort="medium")
    except BackendError as e:
        reason = e.reason if e.reason in ("offline", "timeout") else "error"
        c.update(status="cannot_verify", reason=reason, sources=[])
        return c
    if res.refused:
        c.update(status="cannot_verify", reason="refused", sources=[])
        return c
    searched = [t for t in res.tool_calls if t.get("name") in SEARCH_TOOLS]
    if not searched:
        c.update(status="cannot_verify", reason="no_search", sources=[])
        return c
    tool_text = "\n".join(res.tool_results) + "\n" + json.dumps(
        [t.get("input") for t in res.tool_calls], ensure_ascii=False)
    data = res.data
    sources = _provenance_filter(data.get("sources", []), tool_text)
    status = data["status"]
    if status != "cannot_verify" and not sources:
        c.update(status="cannot_verify", reason="no_source", sources=[])
        return c
    c.update(status=status, reason=data.get("reason", "") if status != "cannot_verify"
             else (data.get("reason") or "no_source"), sources=sources)
    if c["status"] == "cannot_verify" and c["reason"] not in ("no_source", "refused"):
        c["reason"] = "no_source"
    return c


def pick_checker(models: list[str], active: list[str]) -> str:
    for pref in ("sonnet",):
        if pref in active:
            return pref
    return active[0] if active else models[0]


def summary(ledger: list[dict]) -> dict:
    left = [c for c in ledger if is_retryable(c)]
    reasons = Counter(c.get("reason") or "pending" for c in left)
    return {"total": len(ledger), "done": len(ledger) - len(left), "left": len(left),
            "reasons": dict(reasons)}


def run_checks(run: Run, backend: Backend, checker: str, lang: str, *,
               only_retryable: bool = True, say=print) -> dict:
    """Check pending/retryable claims one by one, saving after each.
    KeyboardInterrupt stops cleanly, leaving the rest for later."""
    ledger = read_ledger(run)
    try:
        for i, c in enumerate(ledger):
            if not is_retryable(c):
                continue
            say(f"  … {c['id']} {c['text'][:70]}")
            ledger[i] = check_claim(backend, checker, c, context_for(run, c["anchor"]), lang)
            write_ledger(run, ledger)
            say(f"    → {ledger[i]['status']}"
                + (f" ({ledger[i]['reason']})" if ledger[i]["status"] == "cannot_verify" else ""))
    except KeyboardInterrupt:
        say("  (interrupted — progress saved)")
    return summary(ledger)

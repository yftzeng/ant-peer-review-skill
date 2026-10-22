"""Recheck a revised piece against a parent run's findings (Imbad re-review mode).

Gate 1: each reviewer judges every earlier finding from the revised text, never
seeing the author's reply. Gate 2 (only when a reply exists): one call records
what the author claims per finding; whether a claim holds is decided here, from
the gate-1 verdicts, not by the model.
"""
from __future__ import annotations

from collections import Counter

from . import prompts
from .jsonio import read_json, write_json
from .review import FAILED, OK, REFUSED, _parallel, _record, article_view, load_records
from .schemas import RECHECK, RECHECK_CLAIMS
from .workspace import Run

# Lower = less favourable; ties between equally common verdicts go to the lower one.
UNFAVOURABLE = {"MADE_WORSE": 0, "NOT_ADDRESSED": 1, "PARTIALLY": 2, "CANNOT_VERIFY": 3, "FULLY": 4}


def merge_verdicts(by_model: dict[str, str]) -> tuple[str, str]:
    votes = Counter(by_model.values())
    top = max(votes.values())
    best = min((v for v, n in votes.items() if n == top), key=UNFAVOURABLE.get)
    agreement = "unanimous" if len(votes) == 1 else "majority" if top > len(by_model) / 2 \
        else "split"
    return best, agreement


def parent_of(run: Run) -> Run | None:
    pid = read_json(run.path("00-intake.json"), default={}).get("parent")
    return Run(run.root.parent / pid) if pid else None


def earlier_findings(parent: Run) -> list[dict]:
    cons = read_json(parent.path("05-consensus.json"), default={"findings": []})
    return [{"id": f["id"], "anchor_in_earlier_version": f["anchor"], "level": f["level"],
             "severity": f["severity"], "observation": f["observation"], "action": f["action"]}
            for f in cons["findings"]]


def run_recheck(run: Run, backend, models: list[str], lang: str, *, say=print) -> dict | None:
    parent = parent_of(run)
    if parent is None:
        return None
    findings = earlier_findings(parent)
    reviews = load_records(run, "03-reviews")
    active = [m for m in models if reviews.get(m, {}).get("status") == OK] or list(models)
    seats = prompts.assign_seats(models)
    prompt = prompts.recheck_prompt(findings, article_view(run))  # gate 1: no reply in here
    existing = load_records(run, "05b-recheck")
    todo = [m for m in active if existing.get(m, {}).get("status") not in (OK, REFUSED)]

    def one(m: str) -> dict:
        rec = _record(m, backend, lambda: backend.run(
            m, task="recheck", system=prompts.recheck_system(lang, seats.get(m)), prompt=prompt,
            schema=RECHECK))
        write_json(run.path(f"05b-recheck/{m}.json"), rec)
        say(f"  {'✓' if rec['status'] == OK else '✗'} {m}: {rec['status']}")
        return rec

    _parallel(todo, one)
    recs = load_records(run, "05b-recheck")
    if any(recs.get(m, {}).get("status") == FAILED for m in active):
        from .pipeline import Stop
        raise Stop("recheck: a reviewer failed")
    ids = [f["id"] for f in findings]
    rows = []
    for f in findings:
        by, ev = {}, []
        for m in active:
            rec = recs.get(m, {})
            if rec.get("status") != OK:
                continue
            for v in rec["data"].get("verdicts", []):
                if v["finding"] == f["id"]:
                    by[m] = v["verdict"]
                    if v.get("evidence"):
                        ev.append(f"{m}: {v['evidence']}")
        final, agreement = merge_verdicts(by) if by else ("CANNOT_VERIFY", "none")
        rows.append({"finding": f["id"], "observation": f["observation"], "by_model": by,
                     "final": final, "agreement": agreement, "evidence": ev,
                     "author_claim": "", "claim_supported": None})
    response_path = run.path("00-response.md")
    if response_path.exists() and ids:
        res = backend.run(active[0], task="recheck_claims",
                          system=prompts.recheck_claims_system(lang),
                          prompt=prompts.recheck_claims_prompt(
                              [{"id": f["id"], "observation": f["observation"]} for f in findings],
                              response_path.read_text(encoding="utf-8")),
                          schema=RECHECK_CLAIMS)
        claims = {c["finding"]: c["author_claim"].strip()
                  for c in (res.data or {}).get("claims", []) if c.get("author_claim", "").strip()}
        for r in rows:
            if r["finding"] in claims:
                r["author_claim"] = claims[r["finding"]]
                r["claim_supported"] = r["final"] == "FULLY"
    counts = dict(Counter(r["final"] for r in rows))
    out = {"parent": parent.id, "parent_report": _latest(parent), "verdicts": rows,
           "counts": counts}
    write_json(run.path("05b-recheck.json"), out)
    return out


def _latest(parent: Run) -> int:
    from .report import latest_version
    return latest_version(parent)

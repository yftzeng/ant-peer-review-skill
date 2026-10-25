"""Deterministic synthesis: tally findings, rule red lines, weighted score, grade.

No model call happens here, so recomputing after a fact-check change is free
(D-7). Labels come only from the tally of positions; silence is not agreement.
"""
from __future__ import annotations

from .rubric import final_impact, s_curve_fit
from .schemas import OLD_POSITIONS, RED_LINES

SEV_ORDER = {"critical": 0, "major": 1, "minor": 2}
LEVEL_ORDER = {"macro": 0, "meso": 1, "micro": 2}
RL_SEV = {"none": 0, "low": 1, "medium": 2, "high": 3}
VETO_MIN_SEV = RL_SEV["medium"]
WARN_ONLY_CLAIMS = {"proper_noun"}  # names and translated titles: warn, do not veto


class _UF:
    def __init__(self, items):
        self.p = {i: i for i in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _responses(debates: dict[str, dict], active: list[str]) -> list[tuple[str, dict]]:
    out = []
    for m in active:
        rec = debates.get(m, {})
        if rec.get("status") == "ok":
            for r in rec["data"].get("responses", []):
                out.append((m, dict(r, position=OLD_POSITIONS.get(r.get("position"),
                                                                   r.get("position")))))
    return out


def grade_for(total: float, thresholds: dict[str, float]) -> str:
    if total >= thresholds["excellent"]:
        return "excellent"
    if total >= thresholds["good"]:
        return "good"
    if total >= thresholds["revise"]:
        return "revise"
    return "fail"


def synthesize(*, rubric: dict, reviews: dict[str, dict], debates: dict[str, dict],
               ledger: list[dict], intake: dict, models: list[str],
               thresholds: dict[str, float], rulings: dict[str, str] | None = None) -> dict:
    rulings = rulings or {}
    active = [m for m in models if reviews.get(m, {}).get("status") == "ok"]
    n = len(active)
    from .prompts import assign_seats
    seats = assign_seats(models)
    provenance = [{"model": m, "seat": seats[m], "model_id": reviews.get(m, {}).get("model_id", ""),
                   "status": reviews.get(m, {}).get("status", "missing"),
                   "reason": reviews.get(m, {}).get("reason", ""),
                   "backend": reviews.get(m, {}).get("backend", "")} for m in models]
    warnings = []
    if n < 2:
        warnings.append("fewer_than_two_reviewers")
    if len({p["model_id"].split("-")[0] for p in provenance if p["model_id"]}) <= 1:
        warnings.append("single_vendor_correlated_errors")

    resp = _responses(debates, active)
    claims = {c["id"]: c for c in ledger}
    ref_to_claim = {ref: c for c in ledger for ref in c.get("refs", [])}

    # ---- findings -------------------------------------------------------------
    issues = {f"{m}:{i['id']}": dict(i, model=m)
              for m in active for i in reviews[m]["data"].get("issues", [])}
    uf = _UF(issues)
    for who, r in resp:
        dup = (r.get("duplicate_of") or "").strip()
        if r["position"] == "support" and dup and r["target"] in issues:
            mine = f"{who}:{dup}"
            if mine in issues:
                uf.union(r["target"], mine)
    groups: dict[str, list[str]] = {}
    for gid in issues:
        groups.setdefault(uf.find(gid), []).append(gid)

    findings, unverified = [], []
    for members in groups.values():
        members.sort(key=lambda g: (active.index(issues[g]["model"]), g))
        owners = {issues[g]["model"] for g in members}
        corrob = {w for w, r in resp if r["target"] in members and r["position"] == "support"}
        disputes = [{"model": w, "evidence": r.get("evidence", "")} for w, r in resp
                    if r["target"] in members and r["position"] == "object" and w not in owners]
        supporters = sorted(owners | corrob, key=active.index)
        if disputes:
            label = "SPLIT"
        elif len(supporters) == n and n >= 2:
            label = f"CONSENSUS-{n}"
        elif len(supporters) >= 2:
            label = f"SUPPORTED-{len(supporters)}/{n}"
        else:
            label = "SINGLE"
        lead = issues[members[0]]
        sev = min((issues[g]["severity"] for g in members), key=lambda s: SEV_ORDER.get(s, 9))
        f = {"members": members, "label": label, "supporters": supporters, "dissent": disputes,
             "anchor": lead["anchor"], "level": lead["level"], "dimension": lead["dimension"],
             "observation": lead["observation"], "standard": lead["standard"],
             "why_it_matters": lead["why_it_matters"], "action": lead["action"],
             "severity": sev}
        refs = [ref_to_claim.get(f"{issues[g]['model']}:{k}")
                for g in members for k in issues[g].get("claim_ids", [])]
        weak = [c["id"] for c in refs if c and c["status"] == "cannot_verify"]
        if weak:
            f["unverified_claims"] = sorted(set(weak))
            unverified.append(f)
        else:
            findings.append(f)
    key = lambda f: (SEV_ORDER.get(f["severity"], 9), LEVEL_ORDER.get(f["level"], 9), f["anchor"])
    findings.sort(key=key)
    unverified.sort(key=key)
    for i, f in enumerate(findings, 1):
        f["id"] = f"F{i:02d}"
    for i, f in enumerate(unverified, 1):
        f["id"] = f"U{i:02d}"

    # ---- red lines -------------------------------------------------------------
    unsupported = [c for c in ledger if c["status"] == "unsupported"]
    red = {}
    for k in RED_LINES:
        flaggers, advisory, sev, comments = [], [], 0, []
        for m in active:
            for rl in reviews[m]["data"].get("red_lines", []):
                if rl["key"] == k and rl.get("flag"):
                    s = RL_SEV.get(rl.get("severity", "none"), 0)
                    # Only a medium/high flag supports a veto; low is advisory.
                    (flaggers if s >= VETO_MIN_SEV else advisory).append(m)
                    sev = max(sev, s)
                    comments.append({"model": m, "comment": rl.get("comment", ""),
                                     "anchors": rl.get("anchors", [])})
        tgt = {f"{m}:redline:{k}" for m in flaggers}
        corrob = {w for w, r in resp if r["target"] in tgt and r["position"] == "support"}
        disputes = [{"model": w, "evidence": r.get("evidence", "")} for w, r in resp
                    if r["target"] in tgt and r["position"] == "object" and w not in flaggers]
        supporters = sorted(set(flaggers) | corrob, key=active.index)
        evidence, warns = [], []
        if k == "hallucination":
            for c in unsupported:
                # A name or translation that does not match is a warning, never veto evidence.
                (warns if c.get("type") in WARN_ONLY_CLAIMS else evidence).append(
                    {"claim": c["id"], "text": c["text"]})
        if not supporters and not evidence:
            status = "advisory" if advisory or warns else "clear"
        elif k == "hallucination" and evidence and supporters:
            status = "confirmed"          # evidence first: the ledger outranks an objection
        elif len(supporters) >= 2 and not disputes:
            status = "confirmed"
        else:
            status = "needs_ruling"
        if k in rulings and status == "needs_ruling":
            status = {"confirmed": "confirmed", "dismissed": "dismissed"}[rulings[k]]
            ruled = True
        else:
            ruled = False
        red[k] = {"status": status, "supporters": supporters, "dissent": disputes,
                  "severity": [s for s, v in RL_SEV.items() if v == sev][0],
                  "comments": comments, "evidence": evidence, "warnings": warns,
                  "human_ruling": ruled}

    # ---- scores ----------------------------------------------------------------
    scores = {}
    for d in rubric["dimensions"]:
        by = {}
        for m in active:
            for s in reviews[m]["data"].get("scores", []):
                if s["dimension"] == d["key"]:
                    by[m] = float(s["score"])
        if by:
            vals = list(by.values())
            scores[d["key"]] = {"mean": round(sum(vals) / len(vals), 1),
                                "spread": round(max(vals) - min(vals), 1), "by_model": by,
                                "weight": d["weight"]}
    sc = claims.get("SC1")
    impact_note = None
    if "impact" in scores and sc:
        fit = s_curve_fit(sc.get("stage", ""), intake.get("audience", {}))
        before = scores["impact"]["mean"]
        scores["impact"]["mean"] = round(final_impact(before, fit, sc["status"]), 1)
        impact_note = {"stage": sc.get("stage"), "stage_status": sc["status"], "fit": fit,
                       "reviewer_mean": before, "scored": sc["status"] in ("supported", "partly")}
    wsum = sum(v["weight"] for v in scores.values())
    total = round(sum(v["weight"] * v["mean"] for v in scores.values()) / wsum, 1) if wsum else 0.0
    grade = grade_for(total, thresholds)
    if any(v["status"] == "confirmed" for v in red.values()):
        grade = "fail"
    provisional = any(v["status"] == "needs_ruling" for v in red.values())
    split_scores = [k for k, v in scores.items() if v["spread"] >= 25]

    return {"provenance": provenance, "active": active, "warnings": warnings,
            "scores": scores, "impact_s_curve": impact_note, "total": total, "grade": grade,
            "provisional": provisional, "split_scores": split_scores, "red_lines": red,
            "findings": findings, "unverified_findings": unverified}

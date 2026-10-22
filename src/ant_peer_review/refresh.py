"""Recompute consensus from files on disk, and finalize after a fact-check continue."""
from __future__ import annotations

from .consensus import synthesize
from .factcheck import read_ledger, snapshot
from .jsonio import read_json, write_json
from .report import latest_version, write_report
from .review import load_records
from .workspace import Run


def compute_consensus(run: Run, models: list[str], thresholds: dict[str, float]) -> dict:
    decision = read_json(run.path("08-decision.json"), default={})
    cons = synthesize(rubric=read_json(run.path("02-rubric.json")),
                      reviews=load_records(run, "03-reviews"),
                      debates=load_records(run, "04-debate"),
                      ledger=read_ledger(run), intake=read_json(run.path("00-intake.json")),
                      models=models, thresholds=thresholds,
                      rulings=decision.get("rulings", {}))
    write_json(run.path("05-consensus.json"), cons)
    return cons


def changelog(prev: dict, ledger: list[dict], cons: dict) -> list[str]:
    out = []
    for c in ledger:
        old = prev.get("statuses", {}).get(c["id"])
        if old is None:
            out.append(f"{c['id']}: new claim -> {c['status']}")
        elif old[0] != c["status"]:
            out.append(f"{c['id']}: {old[0]} -> {c['status']}")
    for k, st in cons["red_lines"].items():
        before = prev.get("red_lines", {}).get(k)
        if before and before != st["status"]:
            out.append(f"red line {k}: {before} -> {st['status']}")
    for k, v in cons["scores"].items():
        before = prev.get("scores", {}).get(k)
        if before is not None and before != v["mean"]:
            out.append(f"score {k}: {before} -> {v['mean']}")
    if prev.get("total") != cons["total"]:
        out.append(f"total: {prev.get('total')} -> {cons['total']}")
    if prev.get("grade") != cons["grade"]:
        out.append(f"grade: {prev.get('grade')} -> {cons['grade']}")
    return out


def finalize_factcheck(run: Run, models: list[str], thresholds: dict[str, float],
                       lang: str) -> tuple[str, dict | None]:
    """'unchanged' when the ledger matches the last report, else write the next version."""
    v = latest_version(run)
    ledger = read_ledger(run)
    if v == 0:
        return "no_report", None
    prev = read_json(run.path(f"06-report.v{v}.json"))
    if prev["ledger_snapshot"] == snapshot(ledger):
        return "unchanged", prev
    cons = compute_consensus(run, models, thresholds)
    meta = write_report(run, cons, lang=lang, changelog=changelog(prev, ledger, cons))
    return "updated", meta


def factcheck_continue(run: Run, backend, models: list[str], thresholds: dict[str, float],
                       lang: str, io, *, say=None) -> str:
    """`factcheck <run> --continue`: retry, then offer continue-later or finalize."""
    from .factcheck import pick_checker, run_checks
    from .i18n import T
    from .ui import radio
    t = T(lang)
    say = say or io.say
    reviews = load_records(run, "03-reviews")
    active = [m for m in models if reviews.get(m, {}).get("status") == "ok"]
    from .scholarly import verify_identifiers
    verify_identifiers(run, say=say)
    summ = run_checks(run, backend, pick_checker(models, active), lang, say=say)
    if summ["left"]:
        reasons = ", ".join(f"{k} {v}" for k, v in summ["reasons"].items())
        io.say(t("fc.summary", done=summ["done"], total=summ["total"], left=summ["left"],
                 reasons=reasons))
        choice = radio(io, t, t("fc.choice"), [("later", t("fc.later")),
                                               ("finalize", t("fc.finalize"))], default="later")
        if choice == "later":
            io.say(t("fc.resume_hint", run=run.id))
            return "later"
    status, meta = finalize_factcheck(run, models, thresholds, lang)
    if status == "unchanged":
        io.say(t("fc.unchanged", v=meta["version"]))
    elif status == "updated":
        io.say(t("fc.updated", v=meta["version"]))
    else:
        io.say(t("fc.no_report", run=run.id))
    return status

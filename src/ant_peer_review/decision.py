"""P9 human gate: red-line rulings, plan choice, Style Guide evolution."""
from __future__ import annotations

import re
import shutil
from datetime import datetime

from .i18n import T
from .jsonio import append_jsonl, read_json, read_jsonl, write_json, write_text_atomic
from .store import Store
from .ui import IO, confirm, radio
from .workspace import Run

STYLE_CATEGORIES = {"term", "banned_word", "name"}


def pending_rulings(cons: dict) -> list[str]:
    return [k for k, v in cons["red_lines"].items() if v["status"] == "needs_ruling"]


def ask_rulings(io: IO, t: T, cons: dict) -> dict[str, str]:
    rulings = {}
    for k in pending_rulings(cons):
        v = cons["red_lines"][k]
        io.say(f"{t('redline.' + k)} — {', '.join(v['supporters'])}")
        for c in v["comments"]:
            io.say(f"  {c['model']}: {c['comment']}")
        for d in v["dissent"]:
            io.say(f"  ✗ {d['model']}: {d['evidence']}")
        rulings[k] = radio(io, t, t("decide.rule"), [("confirmed", t("report.rl.confirmed")),
                                                     ("dismissed", t("report.rl.dismissed"))])
    return rulings


def available_plans(run: Run) -> list[str]:
    plans = []
    if run.path("07-revision/A.md").exists():
        plans.append("A")
    if run.path("07-revision/B.md").exists():
        plans.append("B")
    return plans


def write_final(run: Run, choice: str, manual_path: str | None = None) -> str:
    src = {"A": "07-revision/A.md", "B": "07-revision/B.md"}.get(choice)
    final = run.path("final.md")
    if choice == "manual":
        if manual_path:
            shutil.copyfile(manual_path, final)
        elif not final.exists():
            shutil.copyfile(run.path("07-revision/A.md"), final)
    elif src:
        shutil.copyfile(run.path(src), final)
    return str(final)


def record_decision(run: Run, *, choice: str, rulings: dict[str, str], final_path: str | None,
                    brand: str) -> dict:
    prev = read_json(run.path("08-decision.json"), default={})
    rul = dict(prev.get("rulings", {}))
    rul.update(rulings)
    dec = {"choice": choice, "rulings": rul, "final": final_path, "brand": brand,
           "decided_at": datetime.now().isoformat(timespec="seconds")}
    write_json(run.path("08-decision.json"), dec)
    return dec


def style_candidates(store: Store, run: Run, brand: str, min_repeats: int) -> list[dict]:
    """Log this run's style corrections, return (from,to) pairs seen >= min_repeats times."""
    corrections = read_json(run.path("07-revision/corrections.json"), default=[])
    log = read_jsonl(store.corrections_log)
    logged_here = {(e["from"], e["to"]) for e in log if e.get("run") == run.id}
    for c in corrections:
        if c.get("category") in STYLE_CATEGORIES and (c["from"], c["to"]) not in logged_here:
            append_jsonl(store.corrections_log, {"brand": brand, "run": run.id, "from": c["from"],
                                                 "to": c["to"], "category": c["category"]})
            logged_here.add((c["from"], c["to"]))
    log = read_jsonl(store.corrections_log)
    existing = guide_rules(store, brand)
    counts: dict[tuple[str, str], set[str]] = {}
    for e in log:
        if e["brand"] == brand:
            counts.setdefault((e["from"], e["to"]), set()).add(e["run"])
    return [{"from": f, "to": to, "runs": len(r)} for (f, to), r in counts.items()
            if len(r) >= min_repeats and (f, to) not in existing]


def guide_path(store: Store, brand: str):
    safe = re.sub(r"[^\w.-]+", "-", brand).strip("-") or "default"
    return store.style_guides / f"{safe}.md"


def guide_rules(store: Store, brand: str) -> set[tuple[str, str]]:
    p = guide_path(store, brand)
    if not p.exists():
        return set()
    return set(re.findall(r'^- "(.+?)" -> "(.+?)"', p.read_text(encoding="utf-8"), re.M))


def guide_text(store: Store, brand: str) -> str:
    p = guide_path(store, brand)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def write_style_rules(store: Store, brand: str, rules: list[dict]) -> None:
    p = guide_path(store, brand)
    text = p.read_text(encoding="utf-8") if p.exists() else f"# Style guide: {brand}\n\n"
    for r in rules:
        f, to = (" ".join(str(r[k]).split()).replace('"', "'") for k in ("from", "to"))
        text += f'- "{f}" -> "{to}"  (seen in {r["runs"]} runs)\n'
    write_text_atomic(p, text)


def propose_style_rules(io: IO, t: T, store: Store, run: Run, brand: str,
                        min_repeats: int) -> list[dict]:
    cands = style_candidates(store, run, brand, min_repeats)
    if not cands:
        return []
    io.say(t("decide.style_proposal", brand=brand))
    for c in cands:
        io.say(f'  "{c["from"]}" -> "{c["to"]}" ({c["runs"]})')
    if confirm(io, t, t("decide.style_confirm"), default=False):
        write_style_rules(store, brand, cands)
        return cands
    return []


def run_decision(io: IO | None, run: Run, store: Store, *, models: list[str], lang: str,
                 thresholds: dict[str, float], min_repeats: int, choice: str | None = None,
                 rulings: dict[str, str] | None = None, manual_path: str | None = None) -> dict:
    """Interactive when io is given and an argument is missing; otherwise from arguments."""
    from .refresh import compute_consensus
    from .report import write_report
    t = T(lang)
    intake = read_json(run.path("00-intake.json"))
    brand = intake.get("brand") or "default"
    cons = read_json(run.path("05-consensus.json"))
    rulings = dict(rulings or {})
    missing = [k for k in pending_rulings(cons) if k not in rulings]
    if missing and io is not None:
        rulings.update(ask_rulings(io, t, {**cons, "red_lines": {
            k: v for k, v in cons["red_lines"].items() if k in missing}}))
    if rulings:
        record_decision(run, choice="pending", rulings=rulings, final_path=None, brand=brand)
        cons = compute_consensus(run, models, thresholds)
        write_report(run, cons, lang=lang,
                     changelog=[f"ruling {k}: {v}" for k, v in rulings.items()])
    plans = available_plans(run)
    if choice is None:
        if io is None:
            raise ValueError("--choice is required in non-interactive mode")
        opts = [(p, t(f"decide.plan.{p}")) for p in plans] + [("manual", t("decide.plan.manual"))]
        choice = radio(io, t, t("decide.choose"), opts, default=plans[-1] if plans else "manual")
        if choice == "manual" and manual_path is None:
            manual_path = io.ask(t("decide.manual_path") + " ").strip() or None
    if choice not in plans + ["manual"]:
        raise ValueError(f"choice must be one of {plans + ['manual']}")
    final = write_final(run, choice, manual_path)
    dec = record_decision(run, choice=choice, rulings=rulings, final_path=final, brand=brand)
    if io is not None:
        dec["style_rules"] = propose_style_rules(io, t, store, run, brand, min_repeats)
        write_json(run.path("08-decision.json"), dec)
    return dec

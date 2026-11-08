"""P6 rounds 1 and 2: blind independent review, then cross-examination.

Each model's output is its own file, so a resumed phase calls only the models
whose file is missing or failed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import prompts
from .backends.base import Backend, BackendError
from .jsonio import read_json, write_json
from .schemas import DEBATE, REVIEW
from .sources.segments import prompt_view
from .workspace import Run

OK, REFUSED, FAILED = "ok", "refused", "failed"


def article_view(run: Run, keep=None) -> str:
    """keep(doc, paragraph_id) -> bool limits the view (D-0002 parts, the debate's anchors)."""
    segs = read_json(run.path("01-sources/segments.json"), default={})
    scan = read_json(run.path("01-sources/injection-scan.json"), default={})
    manifest = read_json(run.path("01-sources/manifest.json"), default={"items": []})
    origins = {d["doc"]: d.get("origin") or d.get("title") or ""
               for it in manifest["items"] for d in it.get("docs", [])}
    if run.path("01-sources/materials.json").exists():
        origins = {"D1": "(draft)"}  # drafting: the piece is the draft, not the materials
    parts = []
    for doc, doc_segs in segs.items():
        if keep is not None:
            doc_segs = [x for x in doc_segs if keep(doc, x["id"])]
            if not doc_segs:
                continue
        parts.append(f"## Document {doc} {origins.get(doc, '')}".rstrip() + "\n\n"
                     + prompt_view(doc_segs, scan.get("withheld", {})))
    return "\n\n".join(parts)


def load_records(run: Run, folder: str) -> dict[str, dict]:
    d = run.path(folder)
    if not d.exists():
        return {}
    return {p.stem: read_json(p) for p in sorted(d.glob("*.json"))}


def _record(model: str, backend: Backend, fn) -> dict:
    try:
        res = fn()
    except BackendError as e:
        return {"model": model, "status": FAILED, "reason": e.reason, "detail": str(e)[:500],
                "backend": backend.name}
    if res.refused:
        return {"model": model, "model_id": res.model_id, "status": REFUSED,
                "reason": "refused", "detail": res.refusal_detail, "backend": backend.name,
                "cost_usd": res.cost_usd}
    return {"model": model, "model_id": res.model_id, "status": OK, "data": res.data,
            "backend": backend.name, "cost_usd": res.cost_usd}


def _clean_review(data: dict) -> dict:
    for s in data.get("scores", []):
        s["score"] = max(0.0, min(100.0, float(s["score"])))
    seen = set()
    for n, issue in enumerate(data.get("issues", []), 1):
        if issue["id"] in seen or not issue["id"]:
            issue["id"] = f"I{n}x"
        seen.add(issue["id"])
    return data


def _parallel(models: list[str], fn) -> dict[str, dict]:
    if not models:
        return {}
    with ThreadPoolExecutor(max_workers=len(models)) as ex:
        futs = {m: ex.submit(fn, m) for m in models}
        return {m: f.result() for m, f in futs.items()}


def run_round1(run: Run, backend: Backend, models: list[str], lang: str, *,
               style_guide: str = "", say=print) -> dict[str, dict]:
    from . import mapreduce as mr
    intake = read_json(run.path("00-intake.json"))
    rubric = read_json(run.path("02-rubric.json"))
    segs = read_json(run.path("01-sources/segments.json"), default={})
    existing = load_records(run, "03-reviews")
    todo = [m for m in models if existing.get(m, {}).get("status") not in (OK, REFUSED)]
    seats = prompts.assign_seats(models)
    parts = mr.plan_parts(segs)
    in_parts = mr.total_chars(segs) > mr.MAPREDUCE_CHARS and len(parts) > 1   # D-0002

    def call(m: str, system: str, view: str, note: str = "") -> dict:
        prompt = note + prompts.review_prompt(intake, rubric, view, style_guide)
        rec = _record(m, backend, lambda: backend.run(m, task="review", system=system,
                                                      prompt=prompt, schema=REVIEW))
        if rec["status"] == OK:
            rec["data"] = _clean_review(rec["data"])
        return rec

    def by_parts(m: str, system: str) -> dict:
        """S-review-panel-031..032: map, retry refused parts by article, then reduce."""
        done, skipped = [], []
        for part in parts:
            rec = mr.cache(run, m, part["id"]) or mr.cache(run, m, part["id"], call(
                m, system, article_view(run, mr.keep_for(part)), mr.part_note(part, len(parts))))
            if rec["status"] == FAILED:
                return rec
            if rec["status"] == OK:
                done.append((part, rec["data"]))
                continue
            singles = [dict(part, id=f"{part['id']}.{k}", docs=[d], ids=None,
                            chars=mr.seg_chars(segs.get(d, [])))
                       for k, d in enumerate(part["docs"], 1)] if len(part["docs"]) > 1 else []
            if not singles:
                skipped += [mr.skipped_entry(run, d, part["chars"]) for d in part["docs"]]
            for one in singles:
                r = mr.cache(run, m, one["id"]) or mr.cache(run, m, one["id"], call(
                    m, system, article_view(run, mr.keep_for(one)), mr.part_note(part, len(parts))))
                if r["status"] == FAILED:
                    return r
                if r["status"] == OK:
                    done.append((one, r["data"]))
                else:
                    skipped.append(mr.skipped_entry(run, one["docs"][0], one["chars"]))
        total = sum(p["chars"] for p in parts) or 1
        info = {"parts": [{"id": p["id"], "docs": p["docs"], "chars": p["chars"]} for p, _ in done],
                "skipped": skipped}
        if not done or sum(x["chars"] for x in skipped) / total > mr.MOST:
            return {"model": m, "status": REFUSED, "reason": "most_parts_refused",
                    "detail": f"{len(skipped)} article(s) refused", "backend": backend.name,
                    "mapreduce": info}
        titles = {d["doc"]: d.get("title", "") for it in read_json(
            run.path("01-sources/manifest.json"), default={"items": []})["items"]
            for d in it.get("docs", [])}
        red = _record(m, backend, lambda: backend.run(
            m, task="review_reduce", system=mr.REDUCE_SYSTEM + prompts.SHARED_RULES.format(
                lang_name=prompts.LANG_NAMES.get(lang, lang)),
            prompt=mr.reduce_prompt(rubric, done, titles), schema=mr.REDUCE))
        info["reduce"] = red["status"]
        return {"model": m, "status": OK, "data": mr.merge(done, red.get("data"), rubric),
                "backend": backend.name, "mapreduce": info}

    def one(m: str) -> dict:
        say(f"  … {m} ({seats[m]})" + (f" · {len(parts)} parts" if in_parts else ""))
        system = prompts.review_system(lang, seats[m])
        if in_parts:
            rec = by_parts(m, system)
        else:
            rec = call(m, system, article_view(run))
            if rec["status"] == REFUSED and len(parts) > 1:      # a refusal loses only what was refused
                say(f"  … {m}: refused as a whole, retrying in {len(parts)} parts")
                rec = by_parts(m, system)
        rec["seat"] = seats[m]
        write_json(run.path(f"03-reviews/{m}.json"), rec)
        say(f"  {'✓' if rec['status'] == OK else '✗'} {m}: {rec['status']}"
            + (f" ({rec.get('reason')})" if rec["status"] != OK else ""))
        return rec

    _parallel(todo, one)
    return load_records(run, "03-reviews")


def debate_targets(reviews: dict[str, dict], me: str) -> list[dict]:
    out = []
    for m, rec in reviews.items():
        if m == me or rec.get("status") != OK:
            continue
        data = rec["data"]
        for i in data.get("issues", []):
            out.append({"target": f"{m}:{i['id']}", "anchor": i["anchor"], "level": i["level"],
                        "severity": i["severity"], "observation": i["observation"],
                        "action": i["action"]})
        for rl in data.get("red_lines", []):
            if rl.get("flag"):
                out.append({"target": f"{m}:redline:{rl['key']}", "anchors": rl.get("anchors", []),
                            "severity": rl.get("severity"), "comment": rl.get("comment", "")})
    return out


def run_debate(run: Run, backend: Backend, models: list[str], lang: str, *,
               say=print) -> dict[str, dict]:
    reviews = load_records(run, "03-reviews")
    active = [m for m in models if reviews.get(m, {}).get("status") == OK]
    if len(active) < 2:
        say("  (fewer than 2 reviewers answered: no debate round)")
        return {}
    ledger = read_ledger_safe(run)
    article = article_view(run)
    if any(reviews[m].get("mapreduce") for m in active):   # S-review-panel-033: anchored text only
        anchors = {".".join(str(a).split(".")[:2]) for m in active
                   for t in debate_targets({k: reviews[k] for k in active}, m)
                   for a in ([t["anchor"]] if "anchor" in t else t.get("anchors", []))}
        article = article_view(run, keep=lambda doc, sid: sid in anchors)
    intake = read_json(run.path("00-intake.json"), default={})
    existing = load_records(run, "04-debate")
    todo = [m for m in active if existing.get(m, {}).get("status") not in (OK, REFUSED)]
    seats = prompts.assign_seats(models)

    def one(m: str) -> dict:
        system = prompts.debate_system(lang, seats.get(m))
        others = debate_targets({k: reviews[k] for k in active}, m)
        prompt = prompts.debate_prompt(reviews[m]["data"], others, ledger, article,
                                       context=intake.get("context", ""))
        rec = _record(m, backend, lambda: backend.run(m, task="debate", system=system,
                                                      prompt=prompt, schema=DEBATE))
        write_json(run.path(f"04-debate/{m}.json"), rec)
        say(f"  {'✓' if rec['status'] == OK else '✗'} {m}: {rec['status']}")
        return rec

    _parallel(todo, one)
    return load_records(run, "04-debate")


def read_ledger_safe(run: Run) -> list[dict]:
    from .factcheck import read_ledger
    return read_ledger(run)


def phase_complete(records: dict[str, dict], models: list[str]) -> bool:
    return all(records.get(m, {}).get("status") in (OK, REFUSED) for m in models)


def failed_models(records: dict[str, dict], models: list[str]) -> list[str]:
    return [m for m in models if records.get(m, {}).get("status") not in (OK, REFUSED)]


__all__ = ["article_view", "run_round1", "run_debate", "load_records", "phase_complete",
           "failed_models", "debate_targets", "Path"]

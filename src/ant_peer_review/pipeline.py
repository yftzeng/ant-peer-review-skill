"""Runs the phases of one run in order, skipping what is done and unchanged."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import prompts
from .backends.base import Backend, BackendError
from .decision import guide_text, run_decision
from .factcheck import build_ledger, pick_checker, read_ledger, run_checks, write_ledger
from .i18n import T
from .intake import run_intake_interactive
from .jsonio import read_json, write_json, write_text_atomic
from .refresh import compute_consensus
from .report import latest_version, write_report
from .review import failed_models, load_records, run_debate, run_round1
from .revision import run_revision
from .rubric import edit_rubric, propose
from .schemas import DRAFT
from .sources.acquire import failed_items, run_sources
from .sources.crawler import Crawler
from .sources.injection import scan
from .sources.segments import prompt_view, segment
from .store import Config, Store
from .ui import IO, ask_text, phase_line, radio
from .workspace import PHASES, Run

MAX_DRAFT_ROUNDS = 2


class Stop(Exception):
    """Pause the run cleanly (resume later)."""


@dataclass
class Ctx:
    io: IO
    store: Store
    cfg: Config
    backend: Backend
    models: list[str]
    lang: str
    interactive: bool
    crawler: Crawler | None = None
    options: dict = field(default_factory=dict)

    @property
    def t(self) -> T:
        return T(self.lang)

    def say(self, text: str = "") -> None:
        self.io.say(text)


def make_crawler(store: Store) -> Crawler:
    return Crawler(site_profiles=read_json(store.site_profiles, default={}))


# ---- phases -----------------------------------------------------------------

def ph_intake(run: Run, ctx: Ctx) -> None:
    if run.path("00-intake.json").exists():
        return
    if not ctx.interactive:
        raise Stop("intake missing: pass --purpose and --target")
    intake = run_intake_interactive(ctx.io, ctx.t, ctx.lang)
    brand = ask_text(ctx.io, ctx.t("intake.brand")).strip()
    if brand:
        intake["brand"] = brand
    write_json(run.path("00-intake.json"), intake)


def ph_sources(run: Run, ctx: Ctx) -> None:
    crawler = ctx.crawler or make_crawler(ctx.store)
    while True:
        manifest = run_sources(run, crawler, on_progress=lambda e: ctx.say(
            f"  {'✓' if e['status'] == 'ok' else '✗'} #{e['item']} {' '.join(e['value'].split())[:70]}"
            + (f" ({e.get('reason')})" if e["status"] != "ok" else "")
            + (f" ⚠ {e['warning']}" if e.get("warning") else "")))
        bad = failed_items(manifest)
        ok_count = len(manifest["items"]) - len(bad)
        if not bad:
            return
        for b in bad:
            if b.get("kind") == "url":
                ctx.say(ctx.t("sources.lesson_hint", reason=b.get("reason")))
        if not ctx.interactive:
            if ok_count:
                return
            raise Stop("no source could be read")
        act = radio(ctx.io, ctx.t, ctx.t("sources.failed", n=len(bad)), [
            ("retry", ctx.t("sources.retry")), ("continue", ctx.t("sources.continue")),
            ("stop", ctx.t("sources.stop"))], default="retry" if not ok_count else "continue")
        if act == "continue" and ok_count:
            return
        if act == "stop" or (act == "continue" and not ok_count):
            raise Stop("sources")


def ph_rubric(run: Run, ctx: Ctx) -> None:
    intake = read_json(run.path("00-intake.json"))
    rub = propose(intake["audience"])
    weights = ctx.options.get("weights")
    if weights:
        for d in rub["dimensions"]:
            if d["key"] in weights:
                d["weight"] = weights[d["key"]]
        from .rubric import validate_rubric
        validate_rubric(rub)
    if ctx.interactive and not weights:
        rub = edit_rubric(ctx.io, ctx.t, rub)
    write_json(run.path("02-rubric.json"), rub)


def _draft_round(run: Run) -> int:
    return int(run.state().get("draft_round", 0))


def ensure_draft(run: Run, ctx: Ctx, feedback: str = "") -> None:
    """Drafting mode: materials -> draft; the draft becomes the piece under review."""
    intake = read_json(run.path("00-intake.json"))
    if intake["purpose"] != "drafting":
        return
    if run.path("01-sources/materials.json").exists() and not feedback:
        return
    materials = read_json(run.path("01-sources/materials.json"), default=None)
    if materials is None:
        materials = read_json(run.path("01-sources/segments.json"))
        write_json(run.path("01-sources/materials.json"), materials)
    mscan = scan([s for d in materials.values() for s in d], [])
    view = "\n\n".join(prompt_view(d, mscan["withheld"]) for d in materials.values())
    writer = ctx.models[0]
    ctx.say(f"  … draft ({writer})")
    res = ctx.backend.run(writer, task="draft", system=prompts.draft_system(ctx.lang),
                          prompt=prompts.draft_prompt(intake, read_json(run.path("02-rubric.json")),
                                                      view, feedback), schema=DRAFT)
    if res.refused or not res.data:
        raise Stop("draft refused")
    md = f"# {res.data['title']}\n\n" + "\n\n".join(res.data["paragraphs"])
    rnd = _draft_round(run) + 1
    write_text_atomic(run.path(f"01-sources/draft.v{rnd}.md"), md + "\n")
    segs = {"D1": segment(md, 1)}
    write_json(run.path("01-sources/segments.json"), segs)
    write_json(run.path("01-sources/injection-scan.json"), scan(segs["D1"], []))
    st = run.state()
    st["draft_round"] = rnd
    run.save_state(st)


def _handle_failures(run: Run, ctx: Ctx, records: dict, label: str, retry) -> dict:
    while True:
        bad = failed_models(records, ctx.models)
        if not bad:
            return records
        ok_n = len(ctx.models) - len(bad)
        if not ctx.interactive:
            if ok_n >= 1:
                ctx.say(ctx.t("review.continue_without", models=", ".join(bad)))
                return records
            raise Stop(label)
        act = radio(ctx.io, ctx.t, ctx.t("review.failed", models=", ".join(bad)), [
            ("retry", ctx.t("sources.retry")), ("continue", ctx.t("review.without")),
            ("stop", ctx.t("sources.stop"))], default="retry")
        if act == "retry":
            records = retry()
            continue
        if act == "continue" and ok_n >= 1:
            return records
        raise Stop(label)


def ph_review(run: Run, ctx: Ctx) -> None:
    ensure_draft(run, ctx)
    intake = read_json(run.path("00-intake.json"))
    sg = guide_text(ctx.store, intake.get("brand") or "default")
    retry = lambda: run_round1(run, ctx.backend, ctx.models, ctx.lang, style_guide=sg,
                               say=ctx.say)
    _handle_failures(run, ctx, retry(), "review", retry)


def ph_factcheck(run: Run, ctx: Ctx) -> None:
    reviews = load_records(run, "03-reviews")
    ledger = build_ledger(reviews, read_ledger(run), ctx.models)
    write_ledger(run, ledger)
    active = [m for m in ctx.models if reviews.get(m, {}).get("status") == "ok"]
    summ = run_checks(run, ctx.backend, pick_checker(ctx.models, active), ctx.lang, say=ctx.say)
    if summ["left"]:
        reasons = ", ".join(f"{k} {v}" for k, v in summ["reasons"].items())
        ctx.say(ctx.t("fc.summary", done=summ["done"], total=summ["total"], left=summ["left"],
                      reasons=reasons))
        ctx.say(ctx.t("fc.resume_hint", run=run.id))


def ph_debate(run: Run, ctx: Ctx) -> None:
    retry = lambda: run_debate(run, ctx.backend, ctx.models, ctx.lang, say=ctx.say)
    recs = retry()
    if recs:
        reviews = load_records(run, "03-reviews")
        active = [m for m in ctx.models if reviews.get(m, {}).get("status") == "ok"]
        sub = Ctx(**{**ctx.__dict__, "models": active})
        _handle_failures(run, sub, recs, "debate", retry)


def ph_consensus(run: Run, ctx: Ctx) -> None:
    compute_consensus(run, ctx.models, ctx.cfg.grade_thresholds)


def ph_report(run: Run, ctx: Ctx) -> None:
    cons = read_json(run.path("05-consensus.json"))
    intake = read_json(run.path("00-intake.json"))
    if intake["purpose"] == "drafting" and cons["grade"] not in ("excellent", "good") \
            and _draft_round(run) < MAX_DRAFT_ROUNDS \
            and not any(v["status"] == "confirmed" for v in cons["red_lines"].values()):
        feedback = "\n".join(f"- [{f['anchor']}] {f['observation']} -> {f['action']}"
                             for f in cons["findings"])
        ctx.say(ctx.t("draft.again", round=_draft_round(run) + 1))
        ensure_draft(run, ctx, feedback=feedback or "Improve overall quality.")
        for name in ("03-reviews", "04-debate"):
            for p in run.path(name).glob("*.json") if run.path(name).exists() else []:
                p.unlink()
        run.rerun_from("review")
        raise Restart()
    meta = write_report(run, cons, lang=ctx.lang)
    path = run.path(f"06-report.v{meta['version']}.md")
    confirmed = [k for k, v in cons["red_lines"].items() if v["status"] == "confirmed"]
    ctx.say(ctx.t("report.done", path=str(path), total=cons["total"],
                  grade=ctx.t("report.grade." + cons["grade"])))
    if confirmed:
        ctx.say(ctx.t("report.veto", keys=", ".join(confirmed)))
    for p in meta["lint"]:
        ctx.say(f"  ⚠ lint: {p}")


def ph_revision(run: Run, ctx: Ctx) -> None:
    out = run_revision(run, ctx.backend, ctx.models, ctx.lang, say=ctx.say)
    c = out["coverage"]
    ctx.say(ctx.t("revision.coverage", a=c["A"], b=c["B"], both=c["both"], none=c["none"]))
    for w in out["warnings"] + out["notes"]:
        ctx.say(f"  · {w}")


def ph_decision(run: Run, ctx: Ctx) -> None:
    if not ctx.interactive:
        ctx.say(ctx.t("decide.hint", run=run.id))
        raise Stop("awaiting decision")
    run_decision(ctx.io, run, ctx.store, models=ctx.models, lang=ctx.lang,
                 thresholds=ctx.cfg.grade_thresholds,
                 min_repeats=ctx.cfg.style_guide_min_repeats)


class Restart(Exception):
    """Drafting loop: start again from the review phase."""


PHASE_FUNCS = {
    "intake": ph_intake, "sources": ph_sources, "rubric": ph_rubric, "review": ph_review,
    "factcheck": ph_factcheck, "debate": ph_debate, "consensus": ph_consensus,
    "report": ph_report, "revision": ph_revision, "decision": ph_decision,
}


def run_pipeline(run: Run, ctx: Ctx) -> str:
    """Returns 'done', 'paused' or 'interrupted'."""
    while True:
        try:
            for ph in PHASES:
                if not run.needs_run(ph):
                    continue
                ctx.say(phase_line(ctx.t("run.phase_start", phase=ph)))
                run.mark(ph, "running")
                try:
                    PHASE_FUNCS[ph](run, ctx)
                except BackendError as e:
                    run.mark(ph, "pending")
                    ctx.say(f"  ✗ {e}")
                    ctx.say(ctx.t("run.resume_hint", run=run.id))
                    return "paused"
                except Stop as e:
                    run.mark(ph, "pending")
                    ctx.say(ctx.t("run.paused", reason=str(e), run=run.id))
                    return "paused"
                except KeyboardInterrupt:
                    run.mark(ph, "pending")
                    ctx.say(ctx.t("run.interrupted", run=run.id))
                    return "interrupted"
                run.mark(ph, "done")
            ctx.say(ctx.t("run.done", path=str(run.root)))
            return "done"
        except Restart:
            continue


__all__ = ["Ctx", "run_pipeline", "Stop", "make_crawler", "latest_version"]

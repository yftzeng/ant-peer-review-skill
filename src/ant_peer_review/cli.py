"""ant-peer-review command line."""
from __future__ import annotations

import argparse
import re
import sys

from . import __version__
from .backends.base import get_backend
from .decision import run_decision
from .i18n import T
from .intake import build_intake_from_args
from .jsonio import read_json, write_json
from .lessons import add_lesson, all_lessons, archive_lesson, lessons_for, promote_if_repeated
from .onboarding import banner, choose_backend, choose_lang, choose_models, effective_models, first_use
from .pipeline import Ctx, run_pipeline
from .refresh import factcheck_continue
from .store import BACKENDS, LANGS, Config, Store
from .ui import IO, ConsoleIO, radio
from .workspace import PHASES, Run, create_run, list_runs, unfinished_runs

EXIT_OK, EXIT_PAUSED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 3, 2, 130


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ant-peer-review",
                                description="Multi-model article drafting and audit workflow.")
    p.add_argument("--version", action="version", version=__version__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--models", help="one-off reviewer list, e.g. opus,fable (not saved)")
    common.add_argument("--backend", choices=BACKENDS + ["fake"], help="one-off backend")
    common.add_argument("--lang", choices=LANGS, help="one-off interface language")
    common.add_argument("--yes", "-y", action="store_true",
                        help="non-interactive: accept defaults, never prompt")
    sub = p.add_subparsers(dest="cmd")

    n = sub.add_parser("new", parents=[common], help="start a new run (default command)")
    n.add_argument("--purpose", choices=["audit", "drafting"])
    n.add_argument("--target", action="append", default=[], help="URL, path or text (repeat)")
    n.add_argument("--audience", help="e.g. expertise=expert+scholar,purpose=trend,lens=custom:regulators "
                        "(several values per layer joined with +)")
    n.add_argument("--brand", help="brand name for the Style Guide")
    n.add_argument("--weights", help="e.g. macro=30,accuracy=40,micro=10,impact=20")

    r = sub.add_parser("resume", parents=[common], help="continue a run")
    r.add_argument("run")
    rr = sub.add_parser("rerun", parents=[common], help="redo a run from a phase")
    rr.add_argument("run")
    rr.add_argument("--from", dest="phase", choices=PHASES, required=True)

    f = sub.add_parser("factcheck", parents=[common], help="retry unfinished fact checks")
    f.add_argument("run")
    f.add_argument("--continue", dest="cont", action="store_true", required=True)
    f.add_argument("--finalize", action="store_true",
                   help="with --yes: finalize instead of saving for later")

    d = sub.add_parser("decide", parents=[common], help="rule red lines and adopt a plan")
    d.add_argument("run")
    d.add_argument("--choice", choices=["A", "B", "manual"])
    d.add_argument("--rule", action="append", default=[], help="red_line=confirmed|dismissed")
    d.add_argument("--file", help="your own final file for --choice manual")

    c = sub.add_parser("config", parents=[common], help="change saved settings")
    c.add_argument("what", choices=["models", "backend", "lang", "show"])

    ls = sub.add_parser("lessons", parents=[common], help="user lessons")
    ls.add_argument("action", choices=["new", "list", "archive"])
    ls.add_argument("arg", nargs="?", help="title for new, id for archive")
    ls.add_argument("--area", default="")
    ls.add_argument("--cause")
    ls.add_argument("--rule", dest="lrule")
    ls.add_argument("--enforced")
    ls.add_argument("--archived", action="store_true")

    sub.add_parser("runs", parents=[common], help="list runs and their status")
    return p


def find_run(store: Store, ref: str) -> Run:
    runs = list_runs(store.runs_dir)
    if ref == "latest" and runs:
        return runs[-1]
    exact = [r for r in runs if r.id == ref]
    if exact:
        return exact[0]
    pref = [r for r in runs if r.id.startswith(ref)]
    if len(pref) == 1:
        return pref[0]
    raise SystemExit(f"run not found or ambiguous: {ref}")


def slug_for(target: str) -> str:
    """A short readable name for the run folder from its first target."""
    from pathlib import Path
    from urllib.parse import urlsplit
    s = target.strip()
    if re.match(r"https?://", s, re.I):
        u = urlsplit(s)
        last = [p for p in u.path.split("/") if p][-1:] or [""]
        return f"{u.hostname or 'url'} {Path(last[0]).stem}".strip()
    first = s.splitlines()[0] if s else "run"
    looks_like_path = "\n" not in s and " " not in s and ("/" in s or "\\" in s)
    if len(s) < 4096 and (looks_like_path or ("\n" not in s and Path(s).expanduser().exists())):
        return Path(s).stem or Path(s).name
    return first.lstrip("#").strip()[:40] or "run"


def parse_weights(s: str | None) -> dict | None:
    if not s:
        return None
    out = {}
    for part in s.split(","):
        k, _, v = part.partition("=")
        out[k.strip()] = int(v)
    if sum(out.values()) != 100:
        raise SystemExit("--weights must sum to 100")
    return out


def load_cfg(args, io: IO, store: Store) -> Config:
    if getattr(args, "yes", False):
        cfg = store.load_config()
        if not cfg.configured:
            store.save_config(cfg)
    else:
        cfg = first_use(io, store, get_backend)
    if args.lang:
        cfg.lang = args.lang
    return cfg


def make_ctx(args, io: IO, store: Store, cfg: Config, *, models=None, backend=None,
             lang=None) -> Ctx:
    backend_name = backend or args.backend or cfg.backend
    return Ctx(io=io, store=store, cfg=cfg, backend=get_backend(backend_name),
               models=models or effective_models(cfg, args.models), lang=lang or cfg.lang,
               interactive=not args.yes,
               options={"weights": parse_weights(getattr(args, "weights", None))})


def run_ctx(args, io: IO, store: Store, cfg: Config, run: Run) -> Ctx:
    """A resumed run uses the models/backend/lang recorded at creation (N-run-workspace-001)."""
    models, backend, lang = run.settings()
    return make_ctx(args, io, store, cfg, models=models, backend=backend,
                    lang=args.lang or lang)


def finish(status: str) -> int:
    return {"done": EXIT_OK, "paused": EXIT_PAUSED, "interrupted": EXIT_INTERRUPTED}[status]


def cmd_new(args, io: IO, store: Store, cfg: Config) -> int:
    t = T(cfg.lang)
    if not args.yes and not args.target:
        pending = unfinished_runs(store.runs_dir)
        if pending:
            io.say(t("run.resume_found"))
            opts = []
            for r in pending[-5:]:
                opts.append((f"c:{r.id}", t("run.resume.continue", run=r.id,
                                            phase=r.first_incomplete())))
            opts.append(("new", t("run.resume.new")))
            choice = radio(io, t, t("run.resume_choice"), opts, default="new")
            if choice.startswith("c:"):
                run = find_run(store, choice[2:])
                ctx = run_ctx(args, io, store, cfg, run)
                io.say(banner(ctx.t, ctx.models))
                return finish(run_pipeline(run, ctx))
    ctx = make_ctx(args, io, store, cfg)
    io.say(banner(ctx.t, ctx.models))
    slug = slug_for(args.target[0]) if args.target else "run"
    intake = None
    if args.target or args.yes:
        try:
            intake = build_intake_from_args(args.purpose or "audit", args.target, args.audience,
                                            lang=ctx.lang)
        except ValueError as e:
            io.say(f"error: {e}")
            return EXIT_USAGE
        if args.brand:
            intake["brand"] = args.brand
    run = create_run(store.runs_dir, slug, models=ctx.models, backend=ctx.backend.name,
                     lang=ctx.lang)
    io.say(ctx.t("run.created", path=str(run.root)))
    if intake:
        write_json(run.path("00-intake.json"), intake)
    return finish(run_pipeline(run, ctx))


def cmd_resume(args, io, store, cfg) -> int:
    run = find_run(store, args.run)
    ctx = run_ctx(args, io, store, cfg, run)
    io.say(banner(ctx.t, ctx.models))
    return finish(run_pipeline(run, ctx))


def cmd_rerun(args, io, store, cfg) -> int:
    run = find_run(store, args.run)
    run.rerun_from(args.phase)
    if args.phase in ("review",):
        for p in run.path("03-reviews").glob("*.json"):
            p.unlink()
    if args.phase in ("review", "debate"):
        for p in run.path("04-debate").glob("*.json") if run.path("04-debate").exists() else []:
            p.unlink()
    return cmd_resume(args, io, store, cfg)


def cmd_factcheck(args, io, store, cfg) -> int:
    run = find_run(store, args.run)
    ctx = run_ctx(args, io, store, cfg, run)
    if args.yes:
        from .factcheck import pick_checker, run_checks
        from .refresh import finalize_factcheck
        from .review import load_records
        reviews = load_records(run, "03-reviews")
        active = [m for m in ctx.models if reviews.get(m, {}).get("status") == "ok"]
        s = run_checks(run, ctx.backend, pick_checker(ctx.models, active), ctx.lang, say=io.say)
        io.say(ctx.t("fc.summary", done=s["done"], total=s["total"], left=s["left"],
                     reasons=", ".join(f"{k} {v}" for k, v in s["reasons"].items())))
        if s["left"] and not args.finalize:
            io.say(ctx.t("fc.resume_hint", run=run.id))
            return EXIT_PAUSED
        status, meta = finalize_factcheck(run, ctx.models, cfg.grade_thresholds, ctx.lang)
        io.say(ctx.t(f"fc.{status}", v=(meta or {}).get("version", 0), run=run.id))
        return EXIT_OK
    status = factcheck_continue(run, ctx.backend, ctx.models, cfg.grade_thresholds,
                                ctx.lang, io)
    return EXIT_PAUSED if status == "later" else EXIT_OK


def cmd_decide(args, io, store, cfg) -> int:
    run = find_run(store, args.run)
    ctx = run_ctx(args, io, store, cfg, run)
    rulings = {}
    for r in args.rule:
        k, _, v = r.partition("=")
        if v not in ("confirmed", "dismissed"):
            io.say("error: --rule needs red_line=confirmed|dismissed")
            return EXIT_USAGE
        rulings[k] = v
    try:
        run_decision(None if args.yes else io, run, store, models=ctx.models, lang=ctx.lang,
                     thresholds=cfg.grade_thresholds, min_repeats=cfg.style_guide_min_repeats,
                     choice=args.choice, rulings=rulings, manual_path=args.file)
    except ValueError as e:
        io.say(f"error: {e}")
        return EXIT_USAGE
    run.mark("decision", "done")
    io.say(ctx.t("run.done", path=str(run.root)))
    return EXIT_OK


def cmd_config(args, io, store, cfg) -> int:
    if args.what == "show":
        io.say(store.config_path.read_text() if store.config_path.exists() else "(no config)")
        return EXIT_OK
    if args.what == "models":
        choose_models(io, cfg, get_backend(args.backend or cfg.backend))
    elif args.what == "backend":
        choose_backend(io, cfg)
    else:
        choose_lang(io, cfg)
    store.save_config(cfg)
    io.say(T(cfg.lang)("setup.saved", path=str(store.config_path)))
    io.say(banner(T(cfg.lang), cfg.models))
    return EXIT_OK


def cmd_lessons(args, io, store, cfg) -> int:
    t = T(cfg.lang)
    if args.action == "list":
        for ls in (lessons_for(store, args.area) if args.area else all_lessons(store)):
            io.say(f"{ls['id']}  [{ls['area']}]  {ls['title']}  — {ls['rule']}")
        return EXIT_OK
    if args.action == "archive":
        archive_lesson(store, args.arg)
        return EXIT_OK
    if not args.arg:
        io.say('error: lessons new "<title>"')
        return EXIT_USAGE
    area = args.area or ("" if args.yes else io.ask(t("lessons.area") + " ").strip())
    cause = args.cause or ("" if args.yes else io.ask(t("lessons.cause") + " ").strip())
    rule = args.lrule or ("" if args.yes else io.ask(t("lessons.rule") + " ").strip())
    enforced = args.enforced or ("judgment" if args.yes else
                                 io.ask(t("lessons.enforced") + " ").strip() or "judgment")
    lid = add_lesson(store, args.arg, area=area, cause=cause, rule=rule, enforced=enforced,
                     archived=args.archived)
    io.say(t("lessons.added", id=lid))
    if not args.yes:
        promote_if_repeated(io, t, store, lid, area)
    return EXIT_OK


def cmd_runs(args, io, store, cfg) -> int:
    for r in list_runs(store.runs_dir):
        nxt = r.first_incomplete()
        intake = read_json(r.path("00-intake.json"), default={})
        io.say(f"{r.id}  {intake.get('purpose', '?'):8}  "
               + (f"next: {nxt}" if nxt else "done"))
    return EXIT_OK


COMMANDS = {"new": cmd_new, "resume": cmd_resume, "rerun": cmd_rerun,
            "factcheck": cmd_factcheck, "decide": cmd_decide, "config": cmd_config,
            "lessons": cmd_lessons, "runs": cmd_runs}


def main(argv: list[str] | None = None, *, io: IO | None = None,
         store: Store | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version"):
        argv = ["new"] + argv
    args = build_parser().parse_args(argv)
    io = io or ConsoleIO()
    store = store or Store()
    try:
        cfg = load_cfg(args, io, store)
        return COMMANDS[args.cmd](args, io, store, cfg)
    except (KeyboardInterrupt, EOFError):
        io.say("\n(interrupted)")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    raise SystemExit(main())

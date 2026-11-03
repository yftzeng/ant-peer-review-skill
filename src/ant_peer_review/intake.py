"""P1-P3: purpose, targets, audience card."""
from __future__ import annotations

import re
from pathlib import Path

from .i18n import T
from .ui import IO, END_TOKENS, checkbox, dim, prompt, question, radio, section

PURPOSES = ["audit", "drafting", "share"]

AUDIENCE_LAYERS: list[tuple[str, list[str]]] = [
    ("expertise", ["public", "beginner", "intermediate", "expert", "scholar"]),
    ("role", ["frontline", "project_owner", "middle_manager", "senior_executive"]),
    ("lens", ["consumer", "sme", "industry_rep", "politician", "national_leader"]),
    ("trust", ["stranger", "prospect", "new_customer", "regular", "loyal_fan", "churned"]),
    ("purpose", ["emotional", "problem_solving", "trend"]),
]
LAYER_KEYS = [k for k, _ in AUDIENCE_LAYERS]
URL_RE = re.compile(r"^https?://\S+$", re.I)


def existing_path(s: str) -> Path | None:
    """S-intake-015: the only check whether typed text names an existing file or folder.
    A long pasted line exceeds the 255-byte limit of one path part; that is text, not an error."""
    if not s or len(s) >= 4096 or "\n" in s:
        return None
    try:
        p = Path(s).expanduser()
        return p if p.exists() else None
    except (OSError, ValueError):
        return None


def classify_target(s: str) -> dict:
    s = s.strip()
    if URL_RE.match(s):
        return {"kind": "url", "value": s}
    if p := existing_path(s):
        return {"kind": "path", "value": str(p.resolve())}
    return {"kind": "text", "value": s}


def ask_purpose(io: IO, t: T) -> str:
    return radio(io, t, t("intake.purpose"),
                 [(p, t(f"intake.purpose.{p}")) for p in PURPOSES], default="audit")


def collect_targets(io: IO, t: T) -> list[dict]:
    while True:
        io.say(question(t("intake.targets_help")))
        targets: list[dict] = []
        empty_run = 0
        while True:
            try:
                line = io.ask(prompt("").rstrip() + " ")
            except EOFError:
                if not targets:
                    raise  # input ended with nothing entered: asking again would never end
                break
            s = line.strip()
            if s in END_TOKENS:
                break
            if not s:
                empty_run += 1
                if empty_run >= 2:
                    break
                continue
            empty_run = 0
            tgt = classify_target(s)
            if tgt["kind"] == "text" and targets and targets[-1]["kind"] == "text":
                targets[-1]["value"] += "\n" + s          # same pasted block
                continue
            targets.append(tgt)
            io.say(dim(t(f"intake.ack.{tgt['kind']}", n=len(targets))))
        if targets:
            return targets
        io.say(t("intake.need_target"))


def normalize_audience(aud: dict | None) -> dict[str, list[str]]:
    """Every layer as a list; older runs stored one string or None per layer."""
    aud = aud or {}
    out = {}
    for k in LAYER_KEYS:
        v = aud.get(k)
        out[k] = [] if v is None else ([v] if isinstance(v, str) else list(v))
    return out


def value_label(t: T, layer: str, value: str) -> str:
    return value[len("custom:"):] if value.startswith("custom:") else t(f"aud.{layer}.{value}")


def audience_label(t: T, layer: str, values) -> str:
    vals = normalize_audience({layer: values})[layer]
    if not vals:
        return t("intake.skipped")
    return "、".join(value_label(t, layer, v) for v in vals)


def _ask_layer(io: IO, t: T, layer: str, options: list[str], current: list[str]) -> list[str]:
    opts = [(o, t(f"aud.{layer}.{o}")) for o in options]
    opts += [(c, c[len("custom:"):]) for c in current if c.startswith("custom:")]
    return checkbox(io, t, t(f"aud.{layer}"), opts, current, allow_custom=True)


def ask_audience(io: IO, t: T, initial: dict | None = None) -> dict:
    aud = normalize_audience(initial) if initial else {}
    if not initial:
        for layer, options in AUDIENCE_LAYERS:
            aud[layer] = _ask_layer(io, t, layer, options, [])
    while True:
        io.say(section(t("intake.card")))
        for layer in LAYER_KEYS:
            io.say(f"  {t(f'aud.{layer}')} {audience_label(t, layer, aud.get(layer))}")
        choices = [("confirm", t("intake.card.confirm"))]
        choices += [(f"edit:{k}", t("intake.card.edit", layer=t(f"aud.{k}").rstrip(":："))) for k in LAYER_KEYS]
        choices += [("redo", t("intake.card.redo"))]
        act = radio(io, t, t("run.resume_choice"), choices, default="confirm")
        if act == "confirm":
            return aud
        if act == "redo":
            for layer, options in AUDIENCE_LAYERS:
                aud[layer] = _ask_layer(io, t, layer, options, aud.get(layer, []))
            continue
        layer = act.split(":", 1)[1]
        aud[layer] = _ask_layer(io, t, layer, dict(AUDIENCE_LAYERS)[layer], aud.get(layer, []))


def parse_audience(spec: str | None) -> dict:
    """'expertise=expert+scholar,lens=custom:regulators' -> lists per layer."""
    aud: dict[str, list[str]] = {k: [] for k in LAYER_KEYS}
    if not spec:
        return aud
    opts = dict(AUDIENCE_LAYERS)
    for part in spec.split(","):
        if not part.strip():
            continue
        if "=" not in part:
            raise ValueError(f"audience entry needs key=value: {part!r}")
        k, v = (x.strip() for x in part.split("=", 1))
        if k not in opts:
            raise ValueError(f"unknown audience layer {k!r}; choose from {LAYER_KEYS}")
        for item in (x.strip() for x in v.split("+")):
            if item.startswith("custom:") and item[7:].strip():
                val = item
            elif item in opts[k]:
                val = item
            else:
                raise ValueError(f"unknown option {item!r} for {k}; choose from {opts[k]} "
                                 "or custom:<text>, joined with +")
            if val not in aud[k]:
                aud[k].append(val)
    return aud


FACT_SOURCES = ["academic"]


def ask_fact_sources(io: IO, t: T, selected=()) -> list[str]:
    """Optional extra fact-check sources; nothing ticked means web search only."""
    return checkbox(io, t, t("intake.fact_sources"),
                    [(s, t(f"intake.fact_sources.{s}")) for s in FACT_SOURCES], list(selected))


def ask_output_langs(io: IO, t: T, default: str, source: str | None = None) -> list[str]:
    """The languages the delivered text is written in, default ticked; at least one."""
    from .outlang import LABELS, OUTPUT_LANGS
    if source and source != default:
        io.say(dim("  " + t("outlang.source", lang=LABELS.get(source, source))))
    return checkbox(io, t, t("outlang.ask"), [(x, LABELS[x]) for x in OUTPUT_LANGS],
                    [default if default in OUTPUT_LANGS else "en"], min_selected=1)


def build_intake_from_args(purpose: str, targets: list[str], audience: str | None,
                           *, lang: str, academic: bool = False, share: dict | None = None,
                           output_langs: list[str] | None = None) -> dict:
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}")
    if not targets:
        raise ValueError("at least one --target is needed")
    out = {"purpose": purpose, "targets": [classify_target(x) for x in targets],
           "audience": parse_audience(audience), "lang": lang,
           "output_langs": output_langs or [lang],
           "fact_sources": ["academic"] if academic else []}
    if purpose == "share":
        out["share"] = share or {}
    return out


def parse_share(platforms: str | None, stance: str | None, take: str | None,
                styles: str | None, home, angle: str | None = None, credit: bool = False) -> dict:
    """--platform x,linkedin --stance recommend --take ... --share-style x=summary+pick
    --angle comment|distill --credit"""
    from .share import ANGLES, DISTILL_STYLES, STANCES
    angle = angle or "comment"
    if angle not in ANGLES:
        raise ValueError(f"--angle must be one of {', '.join(ANGLES)}")
    from .voice import PLATFORMS, SHARE_STYLES, preselected_style
    picked = [p.strip().lower() for p in (platforms or "facebook").split(",") if p.strip()]
    bad = [p for p in picked if p not in PLATFORMS]
    if not picked or bad:
        raise ValueError(f"--platform needs one or more of {', '.join(PLATFORMS)}"
                         + (f"; unknown: {', '.join(bad)}" if bad else ""))
    stance = stance or "recommend"
    if stance not in STANCES:
        raise ValueError(f"--stance must be one of {', '.join(STANCES)}")
    chosen: dict[str, list[str]] = {}
    for part in (styles or "").split(","):
        if "=" in part:
            p, v = (x.strip() for x in part.split("=", 1))
            vals = [x for x in v.split("+") if x]
            if p not in PLATFORMS or any(x not in SHARE_STYLES for x in vals):
                raise ValueError(f"--share-style: platform=style+style with styles from "
                                 f"{', '.join(SHARE_STYLES)}")
            chosen[p] = vals
    from .voice import load_voice
    order = [p for p in PLATFORMS if p in picked]
    out = {"platforms": order, "angle": angle, "stance": stance, "take": (take or "").strip(),
           "styles": {p: chosen.get(p) or [preselected_style(home, p)] for p in order},
           "voices": {p: "own" if load_voice(home, p) else "borrow" for p in order}}
    if angle == "distill":   # no stance; only the styles that carry a principle
        del out["stance"]
        out["credit"] = credit
        out["styles"] = {p: [s for s in chosen.get(p, []) if s in DISTILL_STYLES]
                         or [DISTILL_STYLES[0]] for p in order}
    return out


def ask_share(io: IO, t: T, home, make_voice=None) -> dict:
    """Platforms (ticked where a voice exists), a voice for each platform without one,
    stance, own take, styles per platform (preselected from the voice).
    make_voice(platform, posts, allow, deny) builds and saves a voice; None: cannot."""
    from .platforms import load_platforms
    from .share import ANGLES, DISTILL_STYLES, STANCES
    from .ui import ask_text
    from .voice import (PLATFORMS, SHARE_STYLES, collect_posts, load_voice, never_ask,
                        preselected_style, set_never_ask, voice_for)
    plats = load_platforms(home)
    angle = radio(io, t, t("share.angle"), [(a, t("share.angle." + a)) for a in ANGLES],
                  default="comment")
    distill = angle == "distill"
    have = [p for p in PLATFORMS if load_voice(home, p)]
    platforms = checkbox(io, t, t("share.platforms"),
                         [(p, plats[p]["name"] + ("" if p in have else f"  {t('share.no_voice_mark')}"))
                          for p in PLATFORMS], ["facebook"] + have, min_selected=1)

    def create(p: str) -> bool:
        posts, allow, deny = collect_posts(io, t, plats[p]["name"])
        if not posts or make_voice is None:
            io.say(t("voice.none"))
            return False
        v = make_voice(p, posts, allow, deny)
        io.say(dim("  " + t("voice.saved", platform=plats[p]["name"], n=v["posts"], path="")
                   .rstrip(": ")))
        return True

    voices = {}
    for p in platforms:
        name = plats[p]["name"]
        own = load_voice(home, p)
        if own:
            voices[p] = "own"
            io.say(dim("  " + t("share.voice_applied", platform=name, n=own["posts"],
                                date=own.get("updated_at", "")[:10])))
            continue
        if p in never_ask(home):
            voices[p] = "neutral"
            continue
        _, borrowed = voice_for(home, p)
        opts = [("create", t("share.voice.create", platform=name))]
        if borrowed:
            opts.append(("borrow", t("share.voice.borrow", source=plats[borrowed]["name"],
                                     platform=name)))
        opts += [("neutral", t("share.voice.neutral")), ("never", t("share.voice.never"))]
        ans = radio(io, t, t("share.voice.ask", platform=name), opts,
                    default="borrow" if borrowed else "neutral")
        if ans == "never":
            set_never_ask(home, p)
        if ans == "create" and create(p):
            voices[p] = "own"
        else:   # a voice that could not be created falls back to neutral
            voices[p] = "borrow" if ans == "borrow" else "neutral"
    stance = None if distill else radio(io, t, t("share.stance"),
                                        [(s, t("share.stance." + s)) for s in STANCES],
                                        default="recommend")
    take = ask_text(io, t("share.take")).strip()
    offered = DISTILL_STYLES if distill else SHARE_STYLES
    styles = {}
    for p in platforms:
        while True:
            opts = [(s, t("share.style." + s)) for s in offered]
            if voices[p] == "own":
                opts.append(("__rebuild__", t("share.voice.rebuild")))
            pre = preselected_style(home, p) if voices[p] == "own" else \
                offered[0] if distill else preselected_style(None, p)
            picked = checkbox(io, t, t("share.styles", platform=plats[p]["name"]), opts,
                              [pre if pre in offered else offered[0]], min_selected=1)
            if "__rebuild__" in picked:
                create(p)
                continue
            styles[p] = picked
            break
    out = {"platforms": platforms, "angle": angle, "stance": stance, "take": take,
           "styles": styles, "voices": voices}
    if distill:
        del out["stance"]
        out["credit"] = radio(io, t, t("share.credit"), [("yes", t("share.credit.yes")),
                                                         ("no", t("share.credit.no"))],
                              default="no") == "yes"
    return out


def run_intake_interactive(io: IO, t: T, lang: str) -> dict:
    purpose = ask_purpose(io, t)
    targets = collect_targets(io, t)
    output_langs = ask_output_langs(io, t, lang)
    audience = ask_audience(io, t)
    fact_sources = ask_fact_sources(io, t)
    return {"purpose": purpose, "targets": targets, "audience": audience, "lang": lang,
            "output_langs": output_langs, "fact_sources": fact_sources}

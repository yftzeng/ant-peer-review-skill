"""P1-P3: purpose, targets, audience card."""
from __future__ import annotations

import re
from pathlib import Path

from .i18n import T
from .ui import IO, END_TOKENS, checkbox, dim, prompt, question, radio, section

PURPOSES = ["audit", "drafting"]

AUDIENCE_LAYERS: list[tuple[str, list[str]]] = [
    ("expertise", ["public", "beginner", "intermediate", "expert", "scholar"]),
    ("role", ["frontline", "project_owner", "middle_manager", "senior_executive"]),
    ("lens", ["consumer", "sme", "industry_rep", "politician", "national_leader"]),
    ("trust", ["stranger", "prospect", "new_customer", "regular", "loyal_fan", "churned"]),
    ("purpose", ["emotional", "problem_solving", "trend"]),
]
LAYER_KEYS = [k for k, _ in AUDIENCE_LAYERS]
URL_RE = re.compile(r"^https?://\S+$", re.I)


def classify_target(s: str) -> dict:
    s = s.strip()
    if URL_RE.match(s):
        return {"kind": "url", "value": s}
    p = Path(s).expanduser()
    if len(s) < 4096 and "\n" not in s and p.exists():
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


def ask_fact_sources(io: IO, t: T) -> list[str]:
    """Optional extra fact-check sources; nothing ticked means web search only."""
    return checkbox(io, t, t("intake.fact_sources"),
                    [(s, t(f"intake.fact_sources.{s}")) for s in FACT_SOURCES], [])


def build_intake_from_args(purpose: str, targets: list[str], audience: str | None,
                           *, lang: str, academic: bool = False) -> dict:
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}")
    if not targets:
        raise ValueError("at least one --target is needed")
    return {"purpose": purpose, "targets": [classify_target(x) for x in targets],
            "audience": parse_audience(audience), "lang": lang,
            "fact_sources": ["academic"] if academic else []}


def run_intake_interactive(io: IO, t: T, lang: str) -> dict:
    purpose = ask_purpose(io, t)
    targets = collect_targets(io, t)
    audience = ask_audience(io, t)
    fact_sources = ask_fact_sources(io, t)
    return {"purpose": purpose, "targets": targets, "audience": audience, "lang": lang,
            "fact_sources": fact_sources}

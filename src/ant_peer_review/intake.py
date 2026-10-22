"""P1-P3: purpose, targets, audience card."""
from __future__ import annotations

import re
from pathlib import Path

from .i18n import T
from .ui import IO, END_TOKENS, radio

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
        io.say(t("intake.targets_help"))
        targets: list[dict] = []
        empty_run = 0
        while True:
            try:
                line = io.ask("> ")
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
            io.say(t(f"intake.ack.{tgt['kind']}", n=len(targets)))
        if targets:
            return targets
        io.say(t("intake.need_target"))


def audience_label(t: T, layer: str, value: str | None) -> str:
    if value is None:
        return t("intake.skipped")
    if value.startswith("custom:"):
        return value[len("custom:"):]
    return t(f"aud.{layer}.{value}")


def _ask_layer(io: IO, t: T, layer: str, options: list[str], current: str | None) -> str | None:
    res = radio(io, t, t(f"aud.{layer}"),
                [(o, t(f"aud.{layer}.{o}")) for o in options],
                default=current if current in options else None,
                allow_custom=True, allow_skip=True)
    if res is None or res in options:
        return res
    return "custom:" + res


def ask_audience(io: IO, t: T, initial: dict | None = None) -> dict:
    aud = dict(initial) if initial else {}
    if not initial:
        for layer, options in AUDIENCE_LAYERS:
            aud[layer] = _ask_layer(io, t, layer, options, None)
    while True:
        io.say(t("intake.card"))
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
                aud[layer] = _ask_layer(io, t, layer, options, aud.get(layer))
            continue
        layer = act.split(":", 1)[1]
        options = dict(AUDIENCE_LAYERS)[layer]
        aud[layer] = _ask_layer(io, t, layer, options, aud.get(layer))


def parse_audience(spec: str | None) -> dict:
    aud: dict[str, str | None] = {k: None for k in LAYER_KEYS}
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
        if v.startswith("custom:") and v[7:].strip():
            aud[k] = v
        elif v in opts[k]:
            aud[k] = v
        else:
            raise ValueError(f"unknown option {v!r} for {k}; choose from {opts[k]} or custom:<text>")
    return aud


def build_intake_from_args(purpose: str, targets: list[str], audience: str | None,
                           *, lang: str) -> dict:
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}")
    if not targets:
        raise ValueError("at least one --target is needed")
    return {"purpose": purpose, "targets": [classify_target(x) for x in targets],
            "audience": parse_audience(audience), "lang": lang}


def run_intake_interactive(io: IO, t: T, lang: str) -> dict:
    purpose = ask_purpose(io, t)
    targets = collect_targets(io, t)
    audience = ask_audience(io, t)
    return {"purpose": purpose, "targets": targets, "audience": audience, "lang": lang}

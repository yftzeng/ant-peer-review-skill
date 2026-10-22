"""P5 rubric: default template, audience-driven weights, editing, S-curve fit."""
from __future__ import annotations

import re

from .i18n import T
from .ui import IO, radio

MIN_WEIGHT = 5

TEMPLATE = [
    {"key": "macro", "name": "Structure and logic (Macro)",
     "description": "Is the argument self-consistent, does the paragraph progression hold, "
                    "do the opening and closing hooks grab the reader?",
     "bands": {"high": "Thesis clear and sustained; every section advances it; strong hook.",
               "mid": "Mostly coherent; some sections drift or repeat; hook is generic.",
               "low": "Thesis unclear or contradicted; sections out of order; no hook."}},
    {"key": "accuracy", "name": "Facts and evidence (Accuracy)",
     "description": "Are figures true, sources cited, terminology precise?",
     "bands": {"high": "Every material claim sourced and correct; terms precise.",
               "mid": "Most claims supported; a few unsourced or loosely worded.",
               "low": "Key claims wrong, unsourced or fabricated."}},
    {"key": "micro", "name": "Language and expression (Micro)",
     "description": "Typos, redundancy, ambiguity, punctuation, terminology fit for the audience.",
     "bands": {"high": "Clean, concise, unambiguous, consistent style and punctuation.",
               "mid": "Readable with scattered errors or wordiness.",
               "low": "Frequent errors that hinder reading or change meaning."}},
    {"key": "impact", "name": "Reach and conversion (Impact)",
     "description": "Call-to-action clarity, headline appeal, S-curve stage fit for the "
                    "audience, SEO keyword placement.",
     "bands": {"high": "Compelling headline, clear CTA, fits the topic's adoption stage and "
                       "audience, keywords placed naturally.",
               "mid": "Serviceable headline and CTA; partial fit; keywords present but weak.",
               "low": "No CTA, weak headline, wrong stage for the audience, no keywords."}},
]
DEFAULT_WEIGHTS = {"macro": 30, "accuracy": 30, "micro": 20, "impact": 20}

# (layer, value) -> weight deltas
ADJUST = {
    ("expertise", "expert"): {"accuracy": 10, "micro": -5, "impact": -5},
    ("expertise", "scholar"): {"accuracy": 15, "micro": -5, "impact": -10},
    ("expertise", "public"): {"micro": 5, "impact": 5, "accuracy": -5, "macro": -5},
    ("expertise", "beginner"): {"micro": 5, "macro": 5, "accuracy": -5, "impact": -5},
    ("purpose", "emotional"): {"impact": 10, "accuracy": -5, "macro": -5},
    ("purpose", "problem_solving"): {"macro": 5, "accuracy": 5, "impact": -10},
    ("purpose", "trend"): {"accuracy": 5, "impact": 5, "micro": -10},
    ("role", "senior_executive"): {"macro": 5, "micro": -5},
    ("role", "frontline"): {"micro": 5, "macro": -5},
    ("lens", "politician"): {"accuracy": 5, "impact": -5},
    ("lens", "national_leader"): {"accuracy": 5, "impact": -5},
    ("trust", "stranger"): {"impact": 5, "micro": -5},
    ("trust", "prospect"): {"impact": 5, "micro": -5},
    ("trust", "churned"): {"impact": 5, "macro": -5},
}

S_FIT = {
    "startup": {"good": {"expert", "scholar", "trend"}, "poor": {"public", "emotional"}},
    "tipping_point": {"good": {"intermediate", "expert", "trend", "problem_solving"},
                      "poor": set()},
    "growth": {"good": {"public", "beginner", "intermediate", "problem_solving", "emotional"},
               "poor": {"scholar"}},
    "saturation": {"good": {"public", "beginner", "problem_solving", "emotional"},
                   "poor": {"trend", "expert", "scholar"}},
}
S_CURVE_SHARE = 0.25  # share of the Impact score taken by the S-curve fit when verified


def _rebalance(weights: dict[str, int], fixed: set[str] | None = None) -> dict[str, int]:
    """Scale non-fixed weights so the total is 100; integers, floor MIN_WEIGHT."""
    fixed = fixed or set()
    fixed_sum = sum(weights[k] for k in fixed)
    free = [k for k in weights if k not in fixed]
    if not free:
        if fixed_sum != 100:
            raise ValueError("weights must sum to 100")
        return dict(weights)
    target = 100 - fixed_sum
    if target < MIN_WEIGHT * len(free):
        raise ValueError("fixed weights leave too little for the other dimensions")
    raw = {k: max(weights[k], 1) for k in free}
    total = sum(raw.values())
    scaled = {k: max(MIN_WEIGHT, raw[k] * target / total) for k in free}
    # renormalize after floors, then largest-remainder rounding
    s = sum(scaled.values())
    scaled = {k: v * target / s for k, v in scaled.items()}
    floors = {k: int(v) for k, v in scaled.items()}
    rest = target - sum(floors.values())
    for k in sorted(free, key=lambda k: scaled[k] - floors[k], reverse=True)[:rest]:
        floors[k] += 1
    out = dict(weights)
    out.update(floors)
    return out


def propose(audience: dict) -> dict:
    from .intake import normalize_audience
    w = dict(DEFAULT_WEIGHTS)
    for layer, values in normalize_audience(audience).items():
        known = [v for v in values if (layer, v) in ADJUST]
        for v in known:  # several values in one layer: mean of their shifts
            for k, d in ADJUST[(layer, v)].items():
                w[k] += d / len(known)
    w = {k: max(MIN_WEIGHT, v) for k, v in w.items()}
    w = _rebalance(w)
    dims = [dict(d, weight=w[d["key"]]) for d in TEMPLATE]
    return {"dimensions": dims, "s_curve_share": S_CURVE_SHARE}


def validate_rubric(rubric: dict) -> None:
    total = sum(d["weight"] for d in rubric["dimensions"])
    if total != 100:
        raise ValueError(f"rubric weights sum to {total}, not 100")
    if any(d["weight"] < 1 for d in rubric["dimensions"]):
        raise ValueError("every weight must be at least 1")


def display_name(t: T, d: dict) -> str:
    key = f"dim.{d['key']}"
    label = t(key)
    return d["name"] if label == key else label


def show(io: IO, t: T, rubric: dict) -> None:
    io.say(t("rubric.title"))
    for i, d in enumerate(rubric["dimensions"], 1):
        io.say(f"  {i}) {display_name(t, d)}: {d['weight']}")


def edit_rubric(io: IO, t: T, rubric: dict) -> dict:
    rubric = {**rubric, "dimensions": [dict(d) for d in rubric["dimensions"]]}
    while True:
        show(io, t, rubric)
        act = radio(io, t, t("run.resume_choice"), [
            ("confirm", t("rubric.confirm")), ("weight", t("rubric.edit_weight")),
            ("add", t("rubric.add")), ("remove", t("rubric.remove"))], default="confirm")
        dims = rubric["dimensions"]
        if act == "confirm":
            validate_rubric(rubric)
            return rubric
        if act == "weight":
            key = radio(io, t, t("rubric.which"), [(d["key"], display_name(t, d)) for d in dims])
            val = _ask_int(io, t, t("rubric.new_weight"))
            w = {d["key"]: d["weight"] for d in dims}
            w[key] = val
            try:
                w = _rebalance(w, fixed={key})
            except ValueError as e:
                io.say(str(e))
                continue
            for d in dims:
                d["weight"] = w[d["key"]]
        elif act == "add":
            name = io.ask(t("rubric.add_name") + " ").strip()
            if not name:
                continue
            val = _ask_int(io, t, t("rubric.new_weight"))
            key = "custom-" + (re.sub(r"[^\w]+", "-", name.lower()).strip("-") or "dim")
            if any(d["key"] == key for d in dims):
                io.say(t("ui.invalid"))
                continue
            dims.append({"key": key, "name": name, "weight": val,
                         "description": name, "bands": {}})
            w = _rebalance({d["key"]: d["weight"] for d in dims}, fixed={key})
            for d in dims:
                d["weight"] = w[d["key"]]
        elif act == "remove":
            if len(dims) <= 1:
                io.say(t("ui.invalid"))
                continue
            key = radio(io, t, t("rubric.which"), [(d["key"], display_name(t, d)) for d in dims])
            rubric["dimensions"] = dims = [d for d in dims if d["key"] != key]
            w = _rebalance({d["key"]: d["weight"] for d in dims})
            for d in dims:
                d["weight"] = w[d["key"]]


def _ask_int(io: IO, t: T, prompt: str) -> int:
    while True:
        s = io.ask(prompt + " ").strip()
        if s.isdigit() and 1 <= int(s) <= 95:
            return int(s)
        io.say(t("ui.invalid"))


def s_curve_fit(stage: str, audience: dict) -> float:
    table = S_FIT.get(stage)
    if not table:
        return 50.0
    from .intake import normalize_audience
    aud = normalize_audience(audience)
    vals = {v for v in aud["expertise"] + aud["purpose"] if not v.startswith("custom:")}
    if not vals:
        return 50.0
    good = len(vals & table["good"])
    poor = len(vals & table["poor"])
    return round(max(0.0, min(100.0, 50 + 50 * (good - poor) / len(vals))), 1)


def final_impact(reviewer_impact: float, fit: float | None, stage_status: str) -> float:
    if fit is None or stage_status not in ("supported", "partly"):
        return float(reviewer_impact)
    return (1 - S_CURVE_SHARE) * reviewer_impact + S_CURVE_SHARE * fit

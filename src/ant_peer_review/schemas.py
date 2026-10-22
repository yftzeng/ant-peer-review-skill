"""JSON Schemas for every model step, plus a small validator (subset of draft 2020-12).

The validator covers what the schemas here use: type, properties, required,
additionalProperties=false, items, enum, minimum/maximum.
"""
from __future__ import annotations

from typing import Any

_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "integer": int, "number": (int, float), "null": type(None),
}


def validate(value: Any, schema: dict, path: str = "$") -> list[str]:
    errs: list[str] = []
    typ = schema.get("type")
    if typ:
        types = typ if isinstance(typ, list) else [typ]
        ok = False
        for t in types:
            py = _TYPES[t]
            if isinstance(value, bool) and t in ("integer", "number"):
                continue
            if isinstance(value, py):
                ok = True
                break
        if not ok:
            return [f"{path}: expected {typ}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} < {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} > {schema['maximum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}: missing '{k}'")
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    errs.append(f"{path}: unexpected '{k}'")
        for k, sub in props.items():
            if k in value:
                errs.extend(validate(value[k], sub, f"{path}.{k}"))
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errs.extend(validate(item, schema["items"], f"{path}[{i}]"))
    return errs


def obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props,
            "required": list(props) if required is None else required,
            "additionalProperties": False}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


STR = {"type": "string"}
NUM = {"type": "number"}  # 0-100; clamped in code (structured outputs ignore min/max)
SEVERITY = {"type": "string", "enum": ["critical", "major", "minor"]}
LEVEL = {"type": "string", "enum": ["macro", "meso", "micro"]}
RED_LINES = ["illegal", "hallucination", "pr_landmine", "plagiarism",
             "sensitive_politics", "human_rights"]
CLAIM_TYPES = ["date", "number", "law", "proper_noun", "quote", "s_curve_stage", "other"]
S_STAGES = ["startup", "tipping_point", "growth", "saturation"]
FACT_STATUS = ["supported", "partly", "unsupported", "cannot_verify"]

ISSUE = obj({
    "id": STR,                       # reviewer-local id, e.g. "I3"
    "anchor": STR,                   # "P03.S2", or "missing: <where> - expected <item>; searched: <parts>"
    "level": LEVEL,
    "dimension": STR,                # rubric dimension key
    "observation": STR,
    "standard": STR,                 # which standard is violated
    "why_it_matters": STR,
    "action": STR,                   # requested action
    "severity": SEVERITY,
    "claim_ids": arr(STR),           # fact claims this issue depends on
})

REVIEW = obj({
    "orientation": STR,              # neutral map of the piece, written before judging
    "scores": arr(obj({"dimension": STR, "score": NUM, "rationale": STR, "anchors": arr(STR)})),
    "issues": arr(ISSUE),
    "claims": arr(obj({"id": STR, "anchor": STR, "text": STR,
                       "type": {"type": "string", "enum": CLAIM_TYPES}})),
    "sensitivity": arr(obj({"anchor": STR, "kind": STR, "note": STR})),
    "red_lines": arr(obj({
        "key": {"type": "string", "enum": RED_LINES},
        "flag": {"type": "boolean"},
        "severity": {"type": "string", "enum": ["none", "low", "medium", "high"]},
        "anchors": arr(STR),
        "comment": STR,
    })),
    "s_curve": obj({"stage": {"type": "string", "enum": S_STAGES + ["unknown"]},
                    "evidence_query": STR, "fit_note": STR}),
})

FACTCHECK = obj({
    "status": {"type": "string", "enum": FACT_STATUS},
    "reason": STR,
    "sources": arr(obj({"url": STR, "supporting_excerpt": STR})),
})

# A debate answer supports a finding or objects to it (cf. RFC 7282: objections are
# addressed, not outvoted). Older runs stored "corroborate" / "dispute".
POSITIONS = ["support", "object"]
OLD_POSITIONS = {"corroborate": "support", "dispute": "object"}

DEBATE = obj({
    "responses": arr(obj({
        "target": STR,               # "<model>:<issue id>" or "<model>:redline:<key>"
        "position": {"type": "string", "enum": POSITIONS},
        "evidence": STR,
        "duplicate_of": STR,         # own issue id if it is the same finding, else ""
    })),
})

REVISE_A = obj({
    "paragraphs": arr(obj({"id": STR, "text": STR})),
    "corrections": arr(obj({"from": STR, "to": STR, "category": STR})),
})

REVISE_B = obj({
    "headline_options": arr(STR),
    "paragraphs": arr(obj({"id": STR, "text": STR, "addresses": arr(STR)})),
    "notes": STR,
})

# Change since the earlier version, best to worst (a change-from-baseline scale in
# the spirit of CGI-I). Older runs stored FULLY / PARTIALLY / NOT_ADDRESSED / MADE_WORSE.
CHANGE_VERDICTS = ["RESOLVED", "IMPROVED", "UNCHANGED", "WORSE"]
OLD_VERDICTS = {"FULLY": "RESOLVED", "PARTIALLY": "IMPROVED", "NOT_ADDRESSED": "UNCHANGED",
                "MADE_WORSE": "WORSE"}

REREVIEW = obj({
    "verdicts": arr(obj({
        "issue": STR,
        "verdict": {"type": "string",
                    "enum": CHANGE_VERDICTS},
        "note": STR,
    })),
})

DRAFT = obj({"title": STR, "paragraphs": arr(STR)})

RECHECK_VERDICTS = CHANGE_VERDICTS + ["CANNOT_VERIFY"]

RECHECK = obj({
    "verdicts": arr(obj({
        "finding": STR,
        "verdict": {"type": "string", "enum": RECHECK_VERDICTS},
        "evidence": STR,             # anchor(s) in the revised text
        "note": STR,
    })),
})

RECHECK_CLAIMS = obj({
    "claims": arr(obj({"finding": STR, "author_claim": STR})),
})

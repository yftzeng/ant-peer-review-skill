"""D-0002: a long target is reviewed in parts, then in one series-level pass.

Divide: a series (several documents) is grouped PART_DOCS articles to a part; a single
long document is cut at its headings, about PART_CHARS characters a part.
Map: each reviewer reviews each part alone; a refused part of several articles is
retried one article at a time, and an article still refused is skipped.
Reduce: one series-level call per reviewer sees the parts' maps and issues, not the
text, and gives the macro score and cross-part issues; code merges the rest into one
review record of the usual shape, so the fact-check, debate and consensus are unchanged.
"""
from __future__ import annotations

import json
from collections import Counter

from . import prompts
from .jsonio import read_json, write_json
from .schemas import ISSUE, NUM, STR, arr, obj

MAPREDUCE_CHARS = 80_000
PART_DOCS = 5
PART_CHARS = 30_000
MOST = 0.5            # more than this share of characters skipped: the reviewer refused

REDUCE = obj({"orientation": STR, "macro": obj({"score": NUM, "rationale": STR}),
              "issues": arr(ISSUE)})
REDUCE_SYSTEM = (
    "You review a long piece that was reviewed part by part. You see each part's map, scores "
    "and issues, not its text. Judge what no single part can show: the structure and arc of "
    "the whole, the macro score for the whole (0-100, by the rubric), and issues that span "
    "parts (repetition, a promise made early and never kept, an inconsistency between parts "
    "once their time and scope are compared). Anchor each issue to an id the parts cite, or "
    "write \"missing: <where> - expected <item>; searched: <parts>\". Do not repeat a part's "
    "issue.\n\n")


def seg_chars(segs: list[dict]) -> int:
    return sum(len(s.get("text", "")) for s in segs)


def total_chars(segs: dict[str, list[dict]]) -> int:
    return sum(seg_chars(v) for v in segs.values())


def plan_parts(segs: dict[str, list[dict]]) -> list[dict]:
    """[{id, docs, ids (None = every paragraph of those docs), chars}]."""
    docs = list(segs)
    parts: list[dict] = []
    if len(docs) > 1:
        for i in range(0, len(docs), PART_DOCS):
            group = docs[i:i + PART_DOCS]
            parts.append({"docs": group, "ids": None,
                          "chars": sum(seg_chars(segs[d]) for d in group)})
    elif docs:
        doc, cur, n = docs[0], [], 0
        for s in segs[doc]:
            size = len(s.get("text", ""))
            cut = n + size > PART_CHARS and (s.get("kind") == "heading" or n > 1.5 * PART_CHARS)
            if cur and cut:
                parts.append({"docs": [doc], "ids": cur, "chars": n})
                cur, n = [], 0
            cur.append(s["id"])
            n += size
        if cur:
            parts.append({"docs": [doc], "ids": cur, "chars": n})
    for k, p in enumerate(parts, 1):
        p["id"] = f"G{k}"
    return parts


def keep_for(part: dict):
    ids = set(part["ids"]) if part["ids"] is not None else None
    docs = set(part["docs"])
    return lambda doc, sid: doc in docs and (ids is None or sid in ids)


def part_note(part: dict, n: int) -> str:
    k = int(part["id"].lstrip("G").split(".")[0])
    span = part["docs"][0] if len(part["docs"]) == 1 else f"{part['docs'][0]}..{part['docs'][-1]}"
    return (f"This is part {k} of {n} of a longer piece ({span}). Review this part on its own "
            "terms; the structure of the whole is judged later from every part.\n\n")


def _rename(data: dict, prefix: str) -> dict:
    """Part-prefixed ids for issues and claims, the issues' claim ids renamed alike."""
    claims = {c["id"]: f"{prefix}-{c['id']}" for c in data.get("claims", [])}
    for c in data.get("claims", []):
        c["id"] = claims[c["id"]]
    for i in data.get("issues", []):
        i["id"] = f"{prefix}-{i['id']}"
        i["claim_ids"] = [claims.get(x, f"{prefix}-{x}") for x in i.get("claim_ids", [])]
    return data


def merge(parts: list[tuple[dict, dict]], reduce: dict | None, rubric: dict) -> dict:
    """One review record's data from the parts' (part, data) and the series-level call."""
    scores = []
    for d in rubric["dimensions"]:
        got = [(p["chars"], s) for p, data in parts for s in data.get("scores", [])
               if s["dimension"] == d["key"]]
        if not got:
            continue
        w = sum(c for c, _ in got) or 1
        mean = sum(c * float(s["score"]) for c, s in got) / w
        rationale = "; ".join(f"{p['id']}: {s['rationale']}" for (p, data) in parts
                              for s in data.get("scores", []) if s["dimension"] == d["key"])
        anchors = [a for _, s in got for a in s.get("anchors", [])][:6]
        if d["key"] == "macro" and reduce and reduce.get("macro"):
            mean, rationale = float(reduce["macro"]["score"]), reduce["macro"].get("rationale", "")
        scores.append({"dimension": d["key"], "score": round(max(0.0, min(100.0, mean)), 1),
                       "rationale": rationale[:2000], "anchors": anchors})
    issues, claims, sens = [], [], []
    for p, data in parts:
        data = _rename(json.loads(json.dumps(data)), p["id"])
        issues += data.get("issues", [])
        claims += data.get("claims", [])
        sens += data.get("sensitivity", [])
    if reduce:
        issues += [dict(i, id=f"S-{i['id']}") for i in reduce.get("issues", [])]
    order = ["none", "low", "medium", "high"]
    red: dict[str, dict] = {}
    for p, data in parts:
        for rl in data.get("red_lines", []):
            cur = red.setdefault(rl["key"], {"key": rl["key"], "flag": False, "severity": "none",
                                             "anchors": [], "comment": ""})
            if rl.get("flag"):
                cur["flag"] = True
                if order.index(rl.get("severity", "none")) > order.index(cur["severity"]):
                    cur["severity"] = rl.get("severity", "none")
                cur["anchors"] += [a for a in rl.get("anchors", []) if a not in cur["anchors"]]
                if rl.get("comment"):
                    cur["comment"] = "; ".join(x for x in (cur["comment"], f"{p['id']}: {rl['comment']}") if x)
    stages = Counter(data.get("s_curve", {}).get("stage", "unknown") for _, data in parts)
    stage = next((s for s, _ in stages.most_common() if s != "unknown"), "unknown")
    first = next((data["s_curve"] for _, data in parts
                  if data.get("s_curve", {}).get("stage") == stage), {})
    orient = (reduce or {}).get("orientation") or " ".join(
        f"{p['id']}: {data.get('orientation', '')}" for p, data in parts)
    return {"orientation": orient, "scores": scores, "issues": issues, "claims": claims,
            "sensitivity": sens, "red_lines": list(red.values()),
            "s_curve": {"stage": stage, "evidence_query": first.get("evidence_query", ""),
                        "fit_note": first.get("fit_note", "")}}


def reduce_prompt(rubric: dict, parts: list[tuple[dict, dict]], titles: dict[str, str]) -> str:
    view = [{"part": p["id"], "articles": [titles.get(d, d) for d in p["docs"]],
             "characters": p["chars"], "map": data.get("orientation", ""),
             "scores": {s["dimension"]: s["score"] for s in data.get("scores", [])},
             "issues": [{"id": i["id"], "anchor": i["anchor"], "severity": i["severity"],
                         "observation": i["observation"]} for i in data.get("issues", [])]}
            for p, data in parts]
    return (f"Scoring rubric:\n{prompts.rubric_block(rubric)}\n\n"
            f"The parts, in order (their reviews, not their text):\n"
            f"{prompts.neutralize(json.dumps(view, ensure_ascii=False))}\n")


def skipped_entry(run, doc: str, chars: int) -> dict:
    man = read_json(run.path("01-sources/manifest.json"), default={"items": []})
    d = next((d for it in man["items"] for d in it.get("docs", []) if d["doc"] == doc), {})
    return {"doc": doc, "title": d.get("title", ""), "url": d.get("origin", ""), "chars": chars}


def cache(run, model: str, pid: str, rec: dict | None = None) -> dict | None:
    p = run.path(f"03-reviews/parts/{model}/{pid}.json")
    if rec is None:
        return read_json(p, default=None)
    write_json(p, rec)
    return rec

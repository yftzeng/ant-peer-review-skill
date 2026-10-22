"""P8 tiered revision: A line edit (char-level diff), B developmental edit, re-review."""
from __future__ import annotations

from difflib import SequenceMatcher

from . import prompts
from .backends.base import Backend, BackendError
from .jsonio import read_json, write_json, write_text_atomic
from .review import article_view, load_records
from .schemas import REREVIEW, REVISE_A, REVISE_B
from .workspace import Run


def char_diff(old: str, new: str) -> str:
    """Inline diff: [-removed-]{+added+}, compared character by character (CJK safe)."""
    out = []
    for op, a1, a2, b1, b2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(old[a1:a2])
        if op in ("delete", "replace"):
            out.append(f"[-{old[a1:a2]}-]")
        if op in ("insert", "replace"):
            out.append(f"{{+{new[b1:b2]}+}}")
    return "".join(out)


def paragraphs(run: Run) -> dict[str, dict]:
    segs = read_json(run.path("01-sources/segments.json"), default={})
    return {s["id"]: s for doc in segs.values() for s in doc}


def render_text(paras: dict[str, dict], replaced: dict[str, str]) -> str:
    out = []
    for pid, s in paras.items():
        out.append(replaced.get(pid, s["text"]))
    return "\n\n".join(out) + "\n"


def apply_changes(paras: dict[str, dict], changes: list[dict]) -> tuple[dict[str, str], list[str]]:
    replaced, warnings = {}, []
    for ch in changes:
        if ch["id"] in paras:
            replaced[ch["id"]] = ch["text"].strip()
        else:
            warnings.append(f"unknown paragraph id from model: {ch['id']}")
    return replaced, warnings


def diff_text(paras: dict[str, dict], replaced: dict[str, str]) -> str:
    blocks = []
    for pid, new in replaced.items():
        old = paras[pid]["text"]
        if old == new:
            continue
        block = f"@@ {pid} @@\n- {old}\n+ {new}\n"
        # Inline marks help only for edits; a rewrite reads better as -/+ alone.
        if SequenceMatcher(None, old, new, autojunk=False).ratio() >= 0.5:
            block += f"~ {char_diff(old, new)}\n"
        blocks.append(block)
    return "\n".join(blocks)


def _issue_view(f: dict) -> dict:
    return {k: f[k] for k in ("id", "anchor", "level", "severity", "observation", "standard",
                              "action")}


def split_findings(cons: dict) -> tuple[list[dict], list[dict]]:
    a = [_issue_view(f) for f in cons["findings"] if f["level"] == "micro"]
    b = [_issue_view(f) for f in cons["findings"] if f["level"] in ("macro", "meso")]
    return a, b


def run_revision(run: Run, backend: Backend, models: list[str], lang: str, *, say=print) -> dict:
    cons = read_json(run.path("05-consensus.json"))
    intake = read_json(run.path("00-intake.json"))
    reviews = load_records(run, "03-reviews")
    active = [m for m in models if reviews.get(m, {}).get("status") == "ok"] or list(models)
    writer = active[0]
    checker = active[1] if len(active) > 1 else active[0]
    paras = paragraphs(run)
    article = article_view(run)
    a_issues, b_issues = split_findings(cons)
    out = {"writer": writer, "checker": checker, "warnings": [], "notes": []}

    # --- plan A ---
    say(f"  … A ({writer})")
    try:
        res = backend.run(writer, task="revise_a", system=prompts.revise_a_system(lang),
                          prompt=prompts.revise_prompt(a_issues, article, intake), schema=REVISE_A)
        data = res.data if not res.refused else {"paragraphs": [], "corrections": []}
        if res.refused:
            out["notes"].append(f"A refused by {writer}")
    except BackendError as e:
        raise RuntimeError(f"plan A failed: {e}") from e
    rep_a, warn = apply_changes(paras, data.get("paragraphs", []))
    out["warnings"] += warn
    write_text_atomic(run.path("07-revision/A.md"), render_text(paras, rep_a))
    write_text_atomic(run.path("07-revision/A.diff"), diff_text(paras, rep_a))
    write_json(run.path("07-revision/corrections.json"), data.get("corrections", []))

    # --- plan B ---
    if not b_issues:
        out["notes"].append("no macro/meso findings: plan B skipped")
        write_json(run.path("07-revision/B.json"), {"skipped": True})
    else:
        say(f"  … B ({writer})")
        res = backend.run(writer, task="revise_b", system=prompts.revise_b_system(lang),
                          prompt=prompts.revise_prompt(b_issues, article, intake),
                          schema=REVISE_B)
        bdata = res.data if not res.refused else {"headline_options": [], "paragraphs": [],
                                                  "notes": "refused"}
        rep_b, warn = apply_changes(paras, bdata.get("paragraphs", []))
        out["warnings"] += warn
        b_text = render_text(paras, rep_b)
        write_text_atomic(run.path("07-revision/B.md"), b_text)
        write_text_atomic(run.path("07-revision/B.diff"), diff_text(paras, rep_b))
        write_json(run.path("07-revision/B.json"), bdata)
        addressed = {i for p in bdata.get("paragraphs", []) for i in p.get("addresses", [])}
        targets = [i for i in b_issues if i["id"] in addressed] or b_issues
        say(f"  … re-review ({checker})")
        rr = backend.run(checker, task="rereview", system=prompts.review_system(lang),
                         prompt=prompts.rereview_prompt(targets, b_text), schema=REREVIEW)
        write_json(run.path("07-revision/rereview.json"),
                   {"checker": checker, **(rr.data or {"verdicts": []})})
    write_json(run.path("07-revision/summary.json"), out)
    return out

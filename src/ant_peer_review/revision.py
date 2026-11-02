"""P8 tiered revision: A line edit (char-level diff), B developmental edit, re-review."""
from __future__ import annotations

import re
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


INSERT = "+"


def render_text(paras: dict[str, dict], replaced: dict[str, str]) -> str:
    out = []
    for pid, s in paras.items():
        out.append(replaced.get(pid, s["text"]))
        if pid + INSERT in replaced:
            out.append(replaced[pid + INSERT])
    return "\n\n".join(out) + "\n"


def _norm_id(raw: str) -> str:
    """Accept 'D1.P03', 'D1.P03.S2', 'D1.P03+', and tolerate 'D1.P03a' / trailing notes."""
    m = re.match(r"\s*(D[\w-]*?\.P\d+)(\.S\d+)?\s*(\+|[a-z]\b)?", raw)
    if not m:
        return raw.strip()
    return m.group(1) + (m.group(2) or "") + (INSERT if m.group(3) else "")


def apply_changes(paras: dict[str, dict], changes: list[dict]) -> tuple[dict[str, str], list[str]]:
    """Map model changes onto paragraphs. Sentence ids replace one sentence;
    'P+' ids insert a paragraph after P (several inserts are joined in order)."""
    replaced, warnings = {}, []
    sentence_edits: dict[str, dict[str, str]] = {}
    for ch in changes:
        cid = _norm_id(ch["id"])
        text = ch["text"].strip()
        pid = ".".join(cid.rstrip(INSERT).split(".")[:2])
        if pid not in paras:
            warnings.append(f"unknown paragraph id from model: {ch['id']}")
        elif cid.endswith(INSERT):
            key = pid + INSERT
            replaced[key] = (replaced[key] + "\n\n" + text) if key in replaced else text
        elif cid.count(".") == 2:
            sids = {s["id"] for s in paras[pid]["sentences"]}
            if cid in sids:
                sentence_edits.setdefault(pid, {})[cid] = text
            else:
                warnings.append(f"unknown sentence id from model: {ch['id']}")
        else:
            replaced[pid] = text
    for pid, edits in sentence_edits.items():
        if pid in replaced:
            continue  # a whole-paragraph rewrite wins over sentence edits
        joiner = "" if re.search(r"[\u3000-\u9fff]", paras[pid]["text"]) else " "
        replaced[pid] = joiner.join(edits.get(s["id"], s["text"])
                                    for s in paras[pid]["sentences"])
    return replaced, warnings


def diff_text(paras: dict[str, dict], replaced: dict[str, str]) -> str:
    blocks = []
    for pid, new in replaced.items():
        old = paras.get(pid, {}).get("text", "")  # "" for an inserted paragraph
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


def gate_plan(run: Run, backend: Backend, models: list[str], writer: str, lang: str,
              paras: dict[str, dict], rep: dict[str, str], *, plan: str, every: bool) -> dict:
    """Pass a plan through the writing gate. every=False checks only the paragraphs the
    plan changed (the author's own text stays as written in the light plan A); edited
    paragraphs go back into rep. Failures are listed in 07-revision/<plan>-checks.md."""
    from .gate import (EDIT_RULES, autofix, checks_md, judge, judge_model, rule_check,
                       run_gate)
    from .i18n import T
    from .schemas import STR, arr, obj
    body = [k for k, s in paras.items() if s.get("kind") != "heading"]
    keys = body + [k for k in rep if k.endswith(INSERT)] if every else list(rep)
    original = {k: paras[k]["text"] for k in body}
    texts = {k: rep.get(k, original.get(k, "")) for k in keys}
    texts = {k: v for k, v in texts.items() if v.strip()}
    if not texts:
        return {}
    article = "\n\n".join(original.values())
    titles = [s["text"].lstrip("# ").strip() for s in paras.values() if s.get("kind") == "heading"]
    schema = obj({"paragraphs": arr(obj({"id": STR, "text": STR}))})

    def check(k, text):
        return [i for i in rule_check(text, take=article, protect=titles)
                if i["code"] != "invented_experience"]

    def rewrite(failed):
        ask = "\n".join(f"- id {k}: fix {'; '.join(f['reasons'])}\n  current text:\n"
                        f"{prompts.untrusted(f['text'])}" for k, f in failed.items())
        try:
            r = backend.run(writer, task="revision_edit", schema=schema, effort="medium",
                            timeout=600, system=f"{EDIT_RULES} These are paragraphs of one "
                            f"article, written in {prompts.LANG_NAMES.get(lang, lang)} or the "
                            "article's own language: edit each on its own, keep its meaning "
                            "and its place in the article.",
                            prompt=f"Edit only these paragraphs:\n{ask}")
        except BackendError:
            return {}
        return {x["id"]: x["text"] for x in (r.data or {}).get("paragraphs", [])
                if x.get("id") in failed}

    results = run_gate(texts, rewrite, check=check,
                       fix=lambda k, text: autofix(text, protect=titles),
                       sources=article + "\n" + "\n".join(texts.values()),
                       judge_fn=lambda batch: judge(backend, judge_model(models, writer), batch))
    for k, r in results.items():
        if r["text"] != original.get(k):
            rep[k] = r["text"]
    shown = {k: r for k, r in results.items() if r["changes"] or r["issues"]}
    t = T(lang)
    write_text_atomic(run.path(f"07-revision/{plan}-checks.md"),
                      checks_md(shown, t, t("gate.plan", plan=plan)) if shown else
                      f"# {t('gate.title', what=t('gate.plan', plan=plan))}\n\n—\n")
    return results


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
    drafting = intake.get("purpose") == "drafting"
    gate_plan(run, backend, models, writer, lang, paras, rep_a, plan="A", every=drafting)
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
        gate_plan(run, backend, models, writer, lang, paras, rep_b, plan="B", every=True)
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
    out["coverage"] = write_coverage(run, cons, rep_a, out)
    write_json(run.path("07-revision/summary.json"), out)
    return out


def write_coverage(run: Run, cons: dict, rep_a: dict[str, str], out: dict) -> dict:
    """Which plan handles each finding: A (its micro finding's paragraph was edited),
    B (listed in a rewrite's addresses), both, or none."""
    bdata = read_json(run.path("07-revision/B.json"), default={})
    b_ids = {i for p in bdata.get("paragraphs", []) for i in p.get("addresses", [])}
    a_ids = {i["id"] for i in split_findings(cons)[0]}
    by = {}
    for f in cons["findings"]:
        para = ".".join(f["anchor"].split(".")[:2])
        in_a = f["id"] in a_ids and para in rep_a
        in_b = f["id"] in b_ids
        by[f["id"]] = "both" if in_a and in_b else "A" if in_a else "B" if in_b else "none"
    counts = {k: sum(1 for v in by.values() if v == k) for k in ("A", "B", "both", "none")}
    write_json(run.path("07-revision/coverage.json"), {"by_finding": by, "counts": counts})
    return counts

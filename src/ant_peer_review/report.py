"""P7 report: Markdown health report, versioned, with a linter."""
from __future__ import annotations

import re
from datetime import datetime

from .factcheck import read_ledger, snapshot
from .i18n import T
from .intake import LAYER_KEYS, audience_label, normalize_audience
from .jsonio import read_json, write_json, write_text_atomic
from .workspace import Run

FIVE = ("anchor", "observation", "standard", "why_it_matters", "action")
UNVERIFIED_CLAIMS = re.compile(r"\b(?:I|we) (?:have )?(?:verified|ran|executed|tested|confirmed "
                               r"by running)\b|我(?:已|們已)?(?:驗證|执行|執行|驗算)過?", re.I)
PLACEHOLDER = re.compile(r"TODO|TBD|\{\{|\}\}|<placeholder>|\[insert", re.I)


_MD_SPECIAL = re.compile(r"([\\`*_\[\]()!#|~])")


def cell(text) -> str:
    """Untrusted text as inert Markdown: HTML escaped, link/image/emphasis syntax escaped."""
    s = "" if text is None else str(text)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = _MD_SPECIAL.sub(r"\\\1", s)
    return " ".join(s.split())


def source_urls(sources: list[dict]) -> str:
    from .factcheck import norm_url
    ok = [s["url"].strip() for s in sources if norm_url(s.get("url") or "")]
    return " ".join(u.replace("|", "%7C").replace("<", "%3C").replace(">", "%3E")
                    .replace(" ", "%20") for u in ok)


def latest_version(run: Run) -> int:
    vs = [int(m.group(1)) for p in run.root.glob("06-report.v*.json")
          if (m := re.match(r"06-report\.v(\d+)\.json$", p.name))]
    return max(vs, default=0)


def lint_report(cons: dict, md: str, flagged_excerpts: list[str]) -> list[str]:
    problems = []
    for f in cons["findings"] + cons["unverified_findings"]:
        for k in FIVE:
            if not str(f.get(k, "")).strip():
                problems.append(f"{f.get('id', '?')}: empty field '{k}'")
        for k in FIVE:
            if UNVERIFIED_CLAIMS.search(str(f.get(k, ""))):
                problems.append(f"{f.get('id', '?')}: unsupported verification claim in '{k}'")
    if PLACEHOLDER.search(md):
        problems.append("placeholder text left in report")
    headings = [ln for ln in md.splitlines() if ln.startswith("#")]
    for ex in flagged_excerpts:
        snippet = ex[:40]
        if snippet and any(snippet in h for h in headings):
            problems.append("flagged untrusted text used in a heading")
    return problems


def render(run: Run, cons: dict, *, lang: str, version: int, changelog: list[str]) -> str:
    t = T(lang)
    intake = read_json(run.path("00-intake.json"))
    rubric = read_json(run.path("02-rubric.json"))
    ledger = read_ledger(run)
    scan = read_json(run.path("01-sources/injection-scan.json"), default={"flags": []})
    manifest = read_json(run.path("01-sources/manifest.json"), default={"items": []})
    titles = [d.get("title") or d.get("origin") for it in manifest["items"]
              for d in it.get("docs", [])]
    drafts = sorted(run.path("01-sources").glob("draft.v*.md"))
    if drafts:
        titles = [drafts[-1].read_text(encoding="utf-8").splitlines()[0].lstrip("# ")]
    L = []
    L.append(f"# {t('report.title')} — {cell(titles[0] if titles else run.id)} (v{version})")
    L.append("")
    L.append(f"- {t('report.run')}: `{run.id}`  ·  {datetime.now():%Y-%m-%d %H:%M}")
    L.append(f"- {t('report.purpose')}: {t('intake.purpose.' + intake['purpose'])}")
    audience = normalize_audience(intake.get("audience"))
    aud = "; ".join(f"{t('aud.' + k).rstrip(':：')}: {cell(audience_label(t, k, audience[k]))}"
                    for k in LAYER_KEYS if audience[k])
    L.append(f"- {t('report.audience')}: {aud or t('intake.skipped')}")
    L.append("")
    L.append(f"## {t('report.provenance')}")
    L.append("")
    L.append(f"| {t('report.model')} | ID | {t('report.status')} | backend |")
    L.append("|---|---|---|---|")
    for p in cons["provenance"]:
        L.append(f"| {p['model']} | {cell(p['model_id'])} | {p['status']}"
                 f"{(' (' + p['reason'] + ')') if p['reason'] else ''} | {p['backend']} |")
    for w in cons["warnings"]:
        L.append(f"\n> ⚠ {t('report.warn.' + w)}")
    L.append("")
    L.append(f"## {t('report.dashboard')}")
    L.append("")
    models = cons["active"]
    L.append(f"| {t('report.dimension')} | {t('report.weight')} | {t('report.score')} | "
             f"{t('report.spread')} | " + " | ".join(models) + " |")
    L.append("|---|---:|---:|---:|" + "---:|" * len(models))
    from .rubric import display_name
    names = {d["key"]: display_name(t, d) for d in rubric["dimensions"]}
    for k, v in cons["scores"].items():
        L.append(f"| {cell(names.get(k, k))} | {v['weight']} | {v['mean']} | {v['spread']} | "
                 + " | ".join(str(v["by_model"].get(m, "—")) for m in models) + " |")
    grade = t("report.grade." + cons["grade"])
    if cons["provisional"]:
        grade += f" ({t('report.provisional')})"
    L.append("")
    L.append(f"**{t('report.total')}: {cons['total']}  ·  {t('report.grade')}: {grade}**")
    if cons.get("impact_s_curve"):
        s = cons["impact_s_curve"]
        L.append("")
        L.append(f"- S-curve: {s['stage']} ({s['stage_status']}), fit {s['fit']}, "
                 + (t("report.scurve_scored") if s["scored"] else t("report.scurve_not_scored")))
    if cons["split_scores"]:
        L.append(f"- {t('report.split_scores')}: {', '.join(cons['split_scores'])}")
    L.append("")
    L.append(f"## {t('report.red_lines')}")
    L.append("")
    L.append(f"| {t('report.red_line')} | {t('report.status')} | {t('report.severity')} | "
             f"{t('report.supporters')} | {t('report.dissent')} | {t('report.comment')} |")
    L.append("|---|---|---|---|---|---|")
    for k, v in cons["red_lines"].items():
        comment = "; ".join(f"{c['model']}: {c['comment']} {' '.join(c['anchors'])}"
                            for c in v["comments"])
        if v["evidence"]:
            comment += " " + "; ".join(f"{e['claim']}: {e['text']}" for e in v["evidence"])
        dissent = "; ".join(f"{d['model']}: {d['evidence']}" for d in v["dissent"])
        status = t("report.rl." + v["status"]) + (" ✋" if v.get("human_ruling") else "")
        L.append(f"| {t('redline.' + k)} | {status} | {v['severity']} | "
                 f"{', '.join(v['supporters'])} | {cell(dissent)} | {cell(comment)} |")
    L.append("")
    L.append(f"## {t('report.findings')}")
    L.append("")
    L.append(f"| ID | {t('report.label')} | {t('report.location')} | {t('report.observation')} | "
             f"{t('report.standard')} | {t('report.why')} | {t('report.action')} | "
             f"{t('report.severity')} | {t('report.supporters')} |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for f in cons["findings"]:
        L.append(f"| {f['id']} | {f['label']} | {cell(f['anchor'])} | {cell(f['observation'])} | "
                 f"{cell(f['standard'])} | {cell(f['why_it_matters'])} | {cell(f['action'])} | "
                 f"{f['severity']}/{f['level']} | {', '.join(f['supporters'])} |")
    splits = [f for f in cons["findings"] if f["dissent"]]
    if splits:
        L.append("")
        L.append(f"## {t('report.disagreements')}")
        L.append("")
        for f in splits:
            L.append(f"- **{f['id']}** ({', '.join(f['supporters'])}) — "
                     + "; ".join(f"{d['model']}: {cell(d['evidence'])}" for d in f["dissent"]))
    if cons["unverified_findings"]:
        L.append("")
        L.append(f"## {t('report.unverified')}")
        L.append("")
        for f in cons["unverified_findings"]:
            L.append(f"- **{f['id']}** {cell(f['anchor'])}: {cell(f['observation'])} "
                     f"({', '.join(f['unverified_claims'])})")
    L.append("")
    L.append(f"## {t('report.ledger')}")
    L.append("")
    L.append(f"| ID | {t('report.location')} | {t('report.claim')} | {t('report.status')} | "
             f"{t('report.sources')} |")
    L.append("|---|---|---|---|---|")
    for c in ledger:
        st = c["status"] + (f" ({c['reason']})" if c["status"] == "cannot_verify" else "")
        src = source_urls(c.get("sources", []))
        L.append(f"| {c['id']} | {cell(c['anchor'])} | {cell(c['text'])} | {st} | {src} |")
    if scan.get("flags"):
        L.append("")
        L.append(f"## {t('report.injection')}")
        L.append("")
        L.append(t("report.injection_note"))
        L.append("")
        L.append("```text")
        for fl in scan["flags"]:
            L.append(f"{fl['id']} {fl['location']} [{fl['confidence']}] "
                     f"{','.join(fl['categories'])}: {fl['excerpt'][:200]}".replace("```", "'''"))
        L.append("```")
    if changelog:
        L.append("")
        L.append(f"## {t('report.changelog')}")
        L.append("")
        L.extend(f"- {c}" for c in changelog)
    L.append("")
    L.append(f"<sub>ledger@{snapshot(ledger)}</sub>")
    return "\n".join(L) + "\n"


def write_report(run: Run, cons: dict, *, lang: str, changelog: list[str] | None = None) -> dict:
    version = latest_version(run) + 1
    md = render(run, cons, lang=lang, version=version, changelog=changelog or [])
    scan = read_json(run.path("01-sources/injection-scan.json"), default={"flags": []})
    problems = lint_report(cons, md, [f["excerpt"] for f in scan.get("flags", [])])
    ledger = read_ledger(run)
    meta = {"version": version, "ledger_snapshot": snapshot(ledger),
            "statuses": {c["id"]: [c["status"], c.get("reason", "")] for c in ledger},
            "total": cons["total"], "grade": cons["grade"],
            "red_lines": {k: v["status"] for k, v in cons["red_lines"].items()},
            "scores": {k: v["mean"] for k, v in cons["scores"].items()},
            "lint": problems}
    write_text_atomic(run.path(f"06-report.v{version}.md"), md)
    write_json(run.path(f"06-report.v{version}.json"), meta)
    return meta

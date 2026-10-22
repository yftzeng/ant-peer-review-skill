# ant-peer-review

English | [繁體中文](README.zh-TW.md) | [简体中文](README.zh-CN.md)

A multi-model **audit** and **drafting** workflow for articles: marketing copy, PR, news, technical and opinion pieces. Two or more Claude models review the same text blind to each other. Then each answers the others' findings. A deterministic synthesis turns all of it into a scored report: anchored issues, fact-check results, red-line vetoes, and two revision plans.

It ships as a standalone Python CLI (`ant-peer-review`) plus a Claude skill (`SKILL.md`) that drives it.

## Install

```bash
uv tool install --python 3.12 .          # or: pipx install .
ant-peer-review --version
```

Requirements:
- Python 3.11 or later; there are no runtime dependencies.
- The `claude` CLI (Claude Code), logged in. The default backend calls `claude -p` and uses your Claude Code plan.
- Optional: PDF input needs `pip install 'ant-peer-review[pdf]'` or `pdftotext`.

## Quick start

```bash
ant-peer-review            # interactive: setup on first use, then the whole workflow
```

On first use you choose:
- the interface language: English, 繁體中文 or 简体中文;
- the backend;
- the peer-reviewer models. opus and sonnet are preselected, fable is optional, and at least 2 are needed. Each model gets a probe call before it is saved.

After that, every run starts by printing:

```
Peer reviewers: opus, sonnet   (change: ant-peer-review config models)
```

Non-interactive (scripts, CI, or driven by Claude):

```bash
ant-peer-review new --yes --purpose audit \
  --target https://example.com/post --target ./drafts \
  --audience expertise=public,purpose=trend --brand acme
ant-peer-review decide <run-id> --yes --choice B --rule pr_landmine=dismissed
```

`--backend fake` runs the whole pipeline offline with canned outputs, for demos and smoke tests.

## Workflow

| Phase | What happens |
|---|---|
| intake | Purpose (audit / drafting). Targets, one per line, end with `/done` or two Enters. The audience card has five layers (expertise, decision role, industry/political lens, trust distance, reading purpose); each takes one option, a custom value or skip. |
| sources | Safe crawler and converters produce Markdown with stable ids (`D1.P03.S2`). The prompt-injection scan flags suspect text and withholds it from reviewers. |
| rubric | Four dimensions: Macro (structure), Accuracy (facts), Micro (language), Impact (reach, including the S-curve stage). Weights are proposed from the audience; you edit and confirm them. |
| review | Each reviewer, blind to the others, gives scores, a macro → meso → micro audit, fact claims, a sensitivity scan, 6 red lines and the S-curve stage. |
| factcheck | Claims go into a ledger and are checked with web search. A source counts only if it came back from a search in that call. |
| debate | Each reviewer corroborates or disputes the others' findings, with evidence. |
| consensus | A deterministic tally. Silence is not agreement; disputes are reported as SPLIT. Red-line veto; weighted total and grade. |
| report | `06-report.v<N>.md`: scoreboard, red lines, anchored issues table, disagreements, ledger, injection scan. |
| revision | Plan A is a line edit with a character-level diff, safe for CJK text. Plan B is a developmental edit, re-reviewed by a second model. |
| decision | You rule on contested red lines and adopt A, B or a manual edit, which becomes `final.md`. Recurring corrections are proposed for the brand Style Guide. |

### Red lines (veto)

There are six red lines: (a) illegal, (b) serious factual error / hallucination, (c) brand PR landmine, (d) plagiarism / infringement, (e) sensitive politics, (f) race, gender diversity and human rights.

A red line is confirmed in either of these cases:
- two or more reviewers support it and nobody disputes it;
- for (b) only: an `unsupported` claim in the ledger backs it.

A confirmed red line grades the piece **Fail**, whatever its score. A red line that is contested or backed by only one reviewer waits for your ruling.

### Resume

Every run lives in its own folder, with `state.json` recording each phase's input hashes. If an input changes, every phase downstream of it is re-run.

| Command | What it does |
|---|---|
| `ant-peer-review resume <run>` | Continue from the first unfinished phase. |
| `ant-peer-review rerun <run> --from review` | Redo the run from a chosen phase. |
| `ant-peer-review factcheck <run> --continue` | Retry unverified claims. When it stops, choose **continue another time** or **stop and finalize**. Finalize writes the next report version, with a changelog, only if facts changed. No reviewer is called again. |
| `ant-peer-review runs` | List runs and the next phase of each. |

## Where things are stored

Everything stays on your machine, in the per-user data directory: `~/.local/share/ant-peer-review/`, `%APPDATA%\ant-peer-review` on Windows, or `$ANT_PEER_REVIEW_HOME`.

```
config.toml                language, backend, reviewers, grade thresholds
runs/<date>-<slug>/        one workspace per run
LESSONS.md, lessons/       your lessons (index + verbatim archive), never shipped
site-profiles.json         per-domain crawl rules (blocked, user agent)
style-guides/<brand>.md    Style Guide rules you confirmed
```

Run workspace:

```
state.json  00-intake.json  01-sources/{manifest.json,raw/,normalized/,segments.json,injection-scan.json}
02-rubric.json  03-reviews/<model>.json  factcheck/ledger.jsonl  04-debate/<model>.json
05-consensus.json  06-report.v<N>.{md,json}  07-revision/{A.md,A.diff,B.md,B.diff,rereview.json}
08-decision.json  final.md
```

## Safety

- **Crawler:**
  - Every hop, the first request and each redirect, is checked against private, loopback, link-local and metadata addresses.
  - The connection is pinned to the checked IP, so DNS rebinding cannot reach an internal host.
  - It honours robots.txt and enforces a byte cap and a content-type allowlist.
- **Folder conversion:** refuses symlinks and unknown file types, and hashes each file before and after reading it.
- **Prompt injection:** fetched text is data, never instructions. It reaches models only inside one `<untrusted_content>` block, and the delimiter inside the content is neutralized. Text that looks like an instruction to a reviewer is flagged and withheld.
- **Lessons and Style Guide** are written only when you confirm.

## Development

```bash
python3 -m pytest -q        # 100+ tests; specs live in specs/features/*.md (Gherkin)
```

Try the tool from this checkout: `scripts/try.sh new --backend fake`. All data goes to `./workspaces/`, which git ignores and `.claude/settings.json` blocks Claude from reading, because it holds untrusted crawled content.

The design and its decisions are in [docs/DESIGN.md](docs/DESIGN.md). The reference skills we studied, and what was borrowed from each, are listed in [docs/REFERENCES.md](docs/REFERENCES.md). The `anthropic-api` backend is reserved: its interface exists, and the build order puts it second.

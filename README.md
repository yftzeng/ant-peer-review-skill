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
- Optional, for JavaScript-rendered pages: `uv tool install '.[render]'`, then `playwright install chromium`. Programs' forms come first: a GitHub link is read from its raw README, every request asks for Markdown first, and JSON-LD gives the title, author, date and site (its `articleBody` only stands in for a page with too little text). A failed or thin fetch falls back to one retry, then the headless browser, then the AMP version, then a dated Wayback Machine copy, and finally asks you to paste the text. The crawler never disguises itself as a browser. URLs written inside pasted text (up to 3) are fetched as the article's cited sources: the fact-checker gets their matching paragraphs, labelled as the author's own pick, and they are never reviewed as part of the article.
- The `claude` CLI (Claude Code), logged in. The default backend calls `claude -p` and uses your Claude Code plan.
- Optional: PDF input needs `pip install 'ant-peer-review[pdf]'` or `pdftotext`.

## Quick start

```bash
ant-peer-review            # interactive: setup on first use, then the whole workflow
```

On first use you choose:
- the interface language: English, 繁體中文 or 简体中文;
- the backend;
- the peer-reviewer models. opus and sonnet are preselected, fable is optional. Pick 2 or more so the models split the work and review each other; 1 is allowed after a warning, but then there is no cross-review. Each model gets a probe call before it is saved.

Menus use the arrow keys: ↑/↓ move, Enter chooses, Space ticks a checkbox, number keys also work, `c` adds a custom value, Esc cancels. When input is piped, or `ANT_PEER_REVIEW_PLAIN=1` is set, the menus fall back to typed numbers. Arrow keys are tested on Linux; the Windows key reader has no CI yet.

After that, every run starts by printing:

```
Peer reviewers: opus, sonnet   (change: ant-peer-review config models)
```

Non-interactive (scripts, CI, or driven by Claude):

```bash
ant-peer-review new --yes --purpose audit \
  --target https://example.com/post --target ./drafts \
  --audience expertise=public+beginner,purpose=trend --brand acme
ant-peer-review decide <run-id> --yes --choice B --rule pr_landmine=dismissed
```

`--backend fake` runs the whole pipeline offline with canned outputs, for demos and smoke tests.

**Judging** (score and issues only): `--no-revision` stops at the report, with no revision plans, re-review or decision to make. `--context <text|file>` gives the reviewers a trusted note kept apart from the piece, for example "the source is an RSS feed that strips 。「」 and dashes"; it is not scanned as part of the piece, and the reviewers are told not to ask the author to fix what it explains. A single target of about 200,000 characters (a 30-day series) has been reviewed whole: it is segmented to the end and the reviewers cite its last days.

**Share mode** (`--purpose share`): you read someone else's article and want posts for your own followers. The article is still reviewed and fact-checked (no revision). You pick an angle: **comment** (reuse, extend or critique the article) or **distill** (first an analysis, `share-analysis.md`: the article's purpose, each claim kept, strengthened, qualified, dropped or corrected by the fact-check, a direction (reinforce, oppose or middle) and a thesis someone could dispute; the posts are written from it, open with the topic and its main subject (products, models, benchmarks and related people are named) and leave out the original creators, their companies and sites; the judge checks them against it for platitudes, paraphrase, ignored corrections and a missing subject; in a share run the first target is the article, the rest are references, the posts end with a source line (the article's title and link, so readers have the original to refer to) unless `--no-credit`; `--angle distill`). Then platforms (Facebook, Threads, Instagram, X/Twitter, LinkedIn, LINE; Facebook and those with a voice are ticked, `--platform` defaults to facebook), your stance (recommend, extend, reserved, rebut), an optional take of your own (the only experience the posts may mention), and styles per platform (key points, insight, question, adds to it, quick pick). Output: `share-<platform>-<style>.md` (plain text, within each platform's limits; `data/platforms.json`, overridable), `share-checks.md` and `review.md` (fit to share or not). Every post and every reply passes a writing gate: stock phrases, invented experience, ▋ and other block characters, dashes (none at all), punctuation (replies and revised articles: full-width in Chinese; share posts: the punctuation of your own posts on that platform, otherwise full-width in zh-TW and half-width, keeping 。, in other languages), platform limits, then a second model as judge; failures are rewritten up to twice, then marked. Before the posts, the CLI proposes who they are for: four readers (public, beginner, expert, business) weighted from the topic's adoption stage, maturity and media spread, confirmed by you or passed as `--readers`. Each reader then reports only whether its goal was met; the writer rules on every point and rewrites, the rewrite passes the gate again, at most two rounds (`readers.md`).

**Output languages**: after the content check you tick the languages the delivered text is written in: English (US), 繁體中文（台灣用語）, 简体中文（中国大陆用语）; several at once, the `--lang` language by default (`--output-lang zh-TW,en` when not interactive). Regional usage is checked, not only asked for: terms and spellings with one clear regional equivalent are replaced (軟件 → 軟體 for Taiwan, 软体 → 软件 for mainland China, colour → color), terms with a second local meaning are flagged (項目 → 專案?), and characters of the other script must be fixed; quotes, links and titles are never changed. With several languages each file gets a suffix (`audit.en.md`, `reply-pragmatic.zh-TW.md`, `share-x-summary.en.md`): replies and posts are written once per language, the adopted text is localised by one call per extra language and passes the writing gate (`final-checks.md`). Reports stay in the interface language.

## Workflow

| Phase | What happens |
|---|---|
| intake | Purpose (audit / drafting / share). Targets, one per line, end with `/done` or two Enters. The audience card has five layers (expertise, decision role, industry/political lens, trust distance, reading purpose); each is a checkbox: tick any number of options or add custom values; ticking none skips the layer. Interactively, after the targets (and the feed articles) a content check lists title, author, site, e-mail, date, length and structure; a long text is sampled for it (whole up to 8,000 units, else its key sections, or its beginning, end and 5 random paragraphs when it has no structure). One call to the cheapest selected model adds genre, topic and suggestions, and the audience card, fact sources and brand come preselected; you can change them. |
| sources | Safe crawler and converters produce Markdown with stable ids (`D1.P03.S2`). The prompt-injection scan flags text aimed at the reviewers and withholds the high-confidence cases (overriding instructions, scoring, secrecy, actions); a finding that rests on a withheld paragraph goes to a human, never the score. |
| rubric | Four dimensions: Macro (structure), Accuracy (facts), Micro (language), Impact (reach, including the S-curve stage). Weights are proposed from the audience; you edit and confirm them. |
| review | Each reviewer has a seat by roster order: structure, facts, or skeptic for a third. Blind to the others, each gives scores, a macro → meso → micro audit, fact claims, a sensitivity scan, 6 red lines and the S-curve stage. |
| factcheck | Claims go into a ledger and are checked with web search. A source counts only if it came back from a search in that call. Optionally, if you tick it after the audience or pass `--academic`, cited DOIs and arXiv ids are verified against doi.org, Crossref and arXiv: existence, title match and retractions. |
| debate | Each reviewer supports or objects to the others' findings, with evidence. |
| consensus | A deterministic tally. Silence is not agreement; disputes are reported as SPLIT. Red-line veto; weighted total and grade. |
| report | `06-report.v<N>.md`: scoreboard, red lines, anchored issues table, disagreements, ledger, injection scan. |
| revision | Plan A is a line edit with a character-level diff, safe for CJK text. Plan B is a developmental edit, re-reviewed by a second model. |
| decision | You rule on contested red lines and adopt A, B or a manual edit, which becomes `audit.md` (`draft.md` when drafting). Then `review.md` gathers everything in one report: verdict, summary, key points (each citing its findings), every check with its result and reason, the findings and the review process. For an audit you tick reply styles (all five by default) and get one ready-to-send reply each: `reply-appreciative.md`, `reply-empathetic.md`, `reply-pragmatic.md`, `reply-socratic.md`, `reply-critical.md`, written in the chosen output languages. `ant-peer-review deliver <run>` writes them again. Recurring corrections are proposed for the brand Style Guide. |

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
| `ant-peer-review voice <platform>` / `voice list` | Learn your voice on a platform (x, facebook, threads, instagram, linkedin, line) from 3-5 of your past posts there, with words you allow and words to ban. You rarely need it: the share intake asks for a voice for each chosen platform that has none (create now, borrow the nearest, neutral, or never ask again), and offers to rebuild one next to its styles. Share posts on that platform use it, and its most used style is preselected; a platform without a voice borrows the nearest one. |
| `ant-peer-review more [<run>]` | Pick more articles from the feed of an earlier run (default: the latest feed run), reusing its purpose, audience, brand and fact sources. The list shows 10 a page, oldest first, and marks articles already reviewed; ticking one again re-reviews it. |
| `ant-peer-review rerun <run> --from review` | Redo the run from a chosen phase. |
| `ant-peer-review factcheck <run> --continue` | Retry unverified claims. When it stops, choose **continue another time** or **stop and finalize**. Finalize writes the next report version, with a changelog, only if facts changed. No reviewer is called again. |
| `ant-peer-review runs` | List runs and the next phase of each. |
| `ant-peer-review runs --summary` | One row per run (total, grade, red lines, findings); `--format csv --out f.csv` for spreadsheets. |
| `ant-peer-review recheck <run> --target <revised> [--response reply.md]` | Check an author's revision against that run's findings, with the same reviewers and rubric. Each finding is judged from the revised text first, and only then compared with the author's reply. The report adds a revision check table. |

## Where things are stored

Everything stays on your machine, in the per-user data directory: `~/.local/share/ant-peer-review/`, `%APPDATA%\ant-peer-review` on Windows, or `$ANT_PEER_REVIEW_HOME`.

```
config.toml                language, backend, reviewers, grade thresholds, [fetch] limits (connect 5, read 10, page 30, url_budget 90 seconds)
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
08-decision.json  audit.md (draft.md)  review.md  reply-*.md
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

The design and its decisions are in [docs/DESIGN.md](docs/DESIGN.md); what it draws on is under [References](#references). The `anthropic-api` backend is reserved: its interface exists, and the build order puts it second.

## References

Full list, with what was borrowed and where it lives: [docs/REFERENCES.md](docs/REFERENCES.md).

Review skills studied (all MIT; ideas only, no code or text copied):
- [K-Dense-AI peer-review](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/peer-review/SKILL.md) (MIT)
- [tsingke/thesis-review-skill](https://github.com/tsingke/thesis-review-skill) (MIT)
- [jam-cc/paper-review.skill](https://github.com/jam-cc/paper-review.skill) (MIT)
- [K-Dense-AI paperzilla](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/paperzilla/SKILL.md) (MIT)
- [K-Dense-AI paper-lookup](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/paper-lookup/SKILL.md) (MIT)

Independent public sources behind the other ideas: RFC 7282 (consensus), Altman & Bland 1995 (absence of evidence), Kim et al. 2025 (correlated LLM errors), the Cochrane Handbook (blinded assessment), the CGI-I scale, NASA SWE-059 (traceability), Noble 2017 (responding to reviewers), Toulmin (argument structure), NIST SP 800-86 and AI RMF, OWASP LLM01/LLM05:2025, Greshake et al. 2023 (indirect prompt injection), Unicode UAX #15 / UTS #39, Trojan Source and CWE-367. See [docs/REFERENCES.md §6](docs/REFERENCES.md#6-independent-sources-replace-rows-69).

Four other skills were read during design, but their licences do not allow commercial use (CC BY-NC 4.0, or no licence). Every idea first seen there was traced to an independent source above and renamed; nothing from them is in this repo.

## License

[MIT](LICENSE) © 2026 Yi-Feng Tzeng. Commercial use is allowed.

- No runtime dependencies. The optional extras keep their own licences: `pdf` → pypdf (BSD-3-Clause), `render` → Playwright (Apache-2.0), `test` → pytest (MIT).
- Data fetched at run time (web pages, doi.org, Crossref, arXiv) stays under its owners' terms. The tool stores it in your workspace only; this licence does not cover it.

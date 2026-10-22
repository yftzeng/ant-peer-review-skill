# ant-peer-review — Design

Status: design agreed 2026-10-22; implemented 2026-10-22 (claude-cli backend). See §10 for what the implementation settled.

An article **drafting** and **audit** workflow, shipped as a Claude skill plus a
standalone Python CLI (`ant-peer-review`). Multiple Claude models review the
same text independently, cross-examine each other, and a synthesis step turns
their findings into a scored, anchored report with tiered revisions.

The skill (SKILL.md, prompts, schemas) is English only. The CLI interface is
localized (en, zh-TW, zh-CN). The project ships README.md plus README.zh-TW.md
and README.zh-CN.md.

## 1. Decisions

| ID | Decision | Rejected alternative, and why |
|---|---|---|
| D-1 | Standalone Python CLI owns interaction, state, crawling and model calls | Skill-only inside Claude Code: AskUserQuestion caps at 4 options/question; audience layers have 5-6 |
| D-2 | Model calls go through a `Backend` interface; ship `claude-cli` (`claude -p`) and `anthropic-api` (Anthropic SDK). Chosen at first run | One backend only: `claude-cli` is cheapest for a subscriber (no per-token cost inside plan limits); `anthropic-api` gives schema-guaranteed JSON, batch -50%, predictable cost for teams/CI. **Build order: `claude-cli` first**, `anthropic-api` second |
| D-3 | Claude models only for now; the `Backend` interface does not assume Anthropic so other vendors can be added | Multi-vendor now: more code, more credentials, not needed yet |
| D-4 | Reviewer roster chosen by checkbox at first run (opus + sonnet preselected, fable optional), minimum 2, persisted | Fixed roster: fable costs ~2.5x opus per token; the user decides |
| D-5 | Weighted rubric total **plus** non-compensatory veto: a confirmed red line fails the piece regardless of score | No weights (Imbad0202, K-Dense): the user needs a ranked, weighted total. Weights only (tsingke): a high score could hide a legal problem |
| D-6 | Unverifiable facts are recorded `cannot_verify` and the run continues; a separate command continues fact-checking later | Abort on no network: one flaky source would block the whole review |
| D-7 | When facts change after a report, recompute only what depends on them (Accuracy score, veto (b), issues anchored to those claims); no new debate round | Full re-review: costs about one more run for a local change |
| D-8 | User lessons and site profiles live in one per-user store shared by all runs; never shipped with the skill | Per-brand stores: crawl knowledge is per site, not per brand. Brand-specific rules go to the brand Style Guide instead |
| D-9 | Anchors are stable paragraph/sentence ids on the normalized Markdown (`P07.S2`), not line numbers | Line numbers shift on every edit and mean nothing for crawled HTML |
| D-10 | Revision diffs are character-level (CJK safe), not line-level | `git diff` on a CJK paragraph marks the whole line changed |

## 2. Commands

```
ant-peer-review                         start a new run, or offer to resume an unfinished one
ant-peer-review resume <run-id>         continue a run from its first incomplete phase
ant-peer-review rerun <run-id> --from <phase>   redo a phase and mark everything downstream stale
ant-peer-review factcheck <run-id> --continue   retry pending / retryable cannot_verify claims
ant-peer-review config models           re-show the reviewer checkbox and save
ant-peer-review config backend          choose claude-cli or anthropic-api
ant-peer-review config lang             en | zh-TW | zh-CN
ant-peer-review lessons new "<title>"   add a user lesson (id assigned by the tool)
ant-peer-review runs                    list runs and their phase status
```

One-off override without saving: `--models opus,fable`, `--backend anthropic-api`, `--lang zh-CN`.

Every run prints the active reviewers first:

```
Peer reviewers: opus, sonnet   (change: ant-peer-review config models)
```

## 3. Phases

Each phase reads its inputs from the run folder, writes its outputs there, and
records input hashes in `state.json`. A phase is skipped on resume only when its
outputs exist **and** its input hashes are unchanged; otherwise it and every
downstream phase are marked `stale`.

HITL gates (the user must confirm before the run continues): P0 setup, P3 audience, P5 rubric, P9 final decision.

### P0 Setup and resume
- First use: choose interface language, backend, reviewers (checkbox, minimum 2). Each chosen model gets a one-token probe call so an unavailable model fails here, not mid-review. Saved to the user config.
- Every start: scan `runs/` for unfinished runs and offer **continue / rerun from a phase / start new**.
- `state.json` records the models and backend actually used; resuming a run keeps them, so phases never mix rosters.

### P1 Purpose
Radio: **Drafting** (generate) or **Audit** (existing content).

### P2 Targets
- The user enters targets one per line: a URL, a local folder or file path, or free text. Each entry is classified on the spot and echoed back (`✓ URL #2`, `✓ folder #1 (14 files)`).
- The list ends with `/done` on its own line, or an empty line twice. Ctrl-D is accepted too.
- Sample tips are shown above the prompt in the interface language.

### P3 Audience
- Five layers asked in order. Each layer is a radio list with **Custom** and **Skip**:
  - (a) expertise / explanation cost: general public, beginner, intermediate, expert, scholar
  - (b) decision role: frontline, project owner, middle manager, senior executive
  - (c) industry / political lens: consumer, SME, industry representative, party politician, national leader
  - (d) trust / psychological distance: stranger, observer/prospect, new customer, regular, loyal fan, churned customer
  - (e) reading purpose: emotional resonance, problem solving, trend tracking
- Then an **audience card** summary: confirm / edit layer n / redo all.

### P4 Source acquisition
All fetched or converted content is **untrusted data, never instructions**.

**URLs**: a shared crawler module.
- SSRF guard: resolve the host and reject private, loopback, link-local and metadata addresses; re-check on every redirect.
- Byte cap, timeout, content-type allowlist (text/html, application/pdf).
- One work item per URL, so it can be retried alone. `manifest.json` records url, final url, status, sha256 and fetched_at.
- Site profiles (from user lessons) are applied automatically, e.g. needs JS rendering, blocked, required user agent.
- HTML is converted to Markdown with stable paragraph ids.

**Folders**: a shared converter.
- Symlinks are refused. Only allowlisted types are read (md, txt, html, docx, pdf).
- sha256 of each input is taken before and after conversion. The converter refuses to write into an existing output directory.

**Text**: written straight to `normalized/` as Markdown.

**Injection scan**, adapted from black-yt paper-review-injection-audit:
- What it looks for:
  - hidden CSS (display:none, zero size, near-white text)
  - HTML comments, alt/aria/title text
  - zero-width and other Unicode Cf characters
  - instructions aimed at a reviewer or LLM (8 categories: score, evaluation direction, prescribed wording, fingerprint, instruction priority, target/stage, concealment, tools/data flow)
- Matches are flags, not verdicts. Flagged spans are excluded from review prompts and shown in the report inside an "untrusted evidence" block.

### P5 Rubric
- Default template: four dimensions.

  | Dimension | Covers |
  |---|---|
  | Macro: structure and logic | argument coherence, paragraph progression, opening/closing hook |
  | Accuracy: facts and evidence | data, citations, terminology |
  | Micro: language | typos, redundancy, ambiguity, punctuation, terminology fit for the audience |
  | Impact: reach and conversion | CTA, headline, S-curve, SEO keyword placement |

- The tool proposes weights from the audience card. The user confirms or edits (custom dimensions allowed); the rubric is then locked in `02-rubric.json`.
- Each dimension carries high/mid/low band descriptors, so every score can be explained.
- **S-curve**, inside Impact, has two parts:
  1. Stage: start-up / tipping point / growth / saturation. The stage needs external evidence (coverage volume, search trend, mainstream pickup) and goes through the fact-check ledger. If it is `cannot_verify`, the sub-item is not scored and its weight is redistributed in proportion to the others.
  2. Fit: stage × audience card, read from an editable table in the config. Example: start-up × general public × emotional resonance scores low fit.

### P6 Review (multi-model)
**Round 1, independent.** Every reviewer runs blind to the others and produces:
1. Rubric scores per dimension, each with anchored evidence.
2. Fact claims extracted (dates, figures, laws, proper nouns, quotes) and appended to the fact-check ledger (§4).
3. PR and sensitivity scan: stereotypes, extreme statements, unverified allegations.
4. Red lines, each Y/N with severity, anchored evidence and a comment:
   - (a) illegal content
   - (b) serious factual error / hallucination
   - (c) brand PR landmine
   - (d) plagiarism / infringement
   - (e) sensitive politics
   - (f) race, gender diversity and human rights
5. Hierarchical audit at three levels:
   - Macro (text): off-topic thesis, unbalanced outline, conclusion that does not support the opening
   - Meso (paragraph): unclear topic sentences, abrupt transitions
   - Micro (sentence): grammar, double negatives, passive overuse, typos, full/half-width spacing

**Round 2, cross-examination.** Each reviewer sees the others' findings and answers each one with `corroborate` or `dispute`, with evidence. There is one round only.

**Synthesis.**
- Each weakness is split into sub-claims and tallied per reviewer as raised / corroborated / not-mentioned / disputed. *Not-mentioned is silence, not agreement.*
- Labels: `CONSENSUS-n`, `SPLIT`, `unresolved-dissent`. Disputes are never silently resolved; they appear in the report.
- **Veto rule:** any red line marked Y with evidence by any reviewer must get an explicit ruling. A confirmed red line forces the grade to *Fail*, whatever the total score.
- **Provenance:** the report lists the model, backend and fresh-context status of each reviewer. Reviewers from one vendor have correlated errors, so the report never claims they are independent.
- **Refusals:** a model that refuses (`stop_reason: refusal`) is recorded as *refused* and disclosed. It is never silently dropped from the tally.

### P7 Report
- Dashboard: score per dimension, weighted total, grade (Excellent / Good / Needs revision / Fail), red-line table.
- Anchored issues table. Each issue has five fields: **location → observation → standard violated → why it matters → requested action**.
- `lint_report.py` checks the report:
  - every issue has all fields filled
  - no placeholders are left
  - no unsupported "I verified / I ran" claims
  - flagged untrusted text is never used as a heading

### P8 Tiered revision
- **A, line edit:** the structure is unchanged; fixes typos, grammar and wordiness. Output is a character-level unified diff.
- **B, developmental edit:** rewrites the flagged paragraphs, writes new headlines and strengthens weak evidence. Every change cites the issue ids it addresses.
- After B, a re-review gives each issue a verdict: `FULLY / PARTIALLY / NOT_ADDRESSED / MADE_WORSE`.

### P9 Human decision and Style Guide evolution
- The user adopts A, B or a manual edit. The decision is recorded in `08-decision.json`.
- When a correction recurs N or more times (product-name spelling, banned words), the tool proposes `style-guide-delta.md`. It is written to `style-guides/<brand>.md` only after the user confirms.

### Drafting mode
- P1 = Drafting generates a draft from the targets, the audience card and the rubric, then runs P6 to P8 on it.
- The loop stops at grade Good or better, or after 2 rounds.

## 4. Fact-check ledger

Location: `runs/<run>/factcheck/ledger.jsonl`, one claim per line.

**Claim fields:** `id`, `anchor`, `text`, `type`, `status`, `reason`, `sources[] {url, accessed_at, supporting_excerpt}`, `checked_by`, `updated_at`.

**Status:**
- `pending`
- `supported`
- `partly`
- `unsupported`
- `cannot_verify`, which takes a reason: `offline`, `timeout`, `refused` or `no_source`

**Rules** (from jam-cc and black-yt):
- A search snippet is a lead, not evidence.
- "Not stated in the text" is a different finding from "stated wrongly".
- If a claim stays unverifiable, any criticism built on it is dropped too.

**Two-step calls** on `anthropic-api`: web search with citations cannot be combined with forced JSON output in one call. Step 1 searches and cites; step 2 extracts the structured ledger rows.

**Reports and snapshots:** each report records the ledger snapshot hash it used (`report.v1.md` → `ledger@<hash>`).

`ant-peer-review factcheck <run> --continue` retries only `pending` claims and retryable `cannot_verify` claims (offline, timeout). When it stops before finishing, it shows:

```
Fact-check: 18/30 done, 12 left (offline 9, timeout 3)
  [1] Continue another time   — save, print the resume command, exit
  [2] Stop and finalize       — compare with the last report's snapshot
```

**Stop and finalize:**
- If nothing changed: say "report unchanged" and keep v1.
- If anything changed: write `report.v<n+1>.md` with a changelog that lists each claim whose status changed and the scores and red lines it moved (D-7).
- Claims still unverified are listed in the report as such.

## 5. Run workspace

```
runs/<YYYYMMDD-HHMM>-<slug>/
  state.json                 phases, status, input hashes, models, backend, lang
  00-intake.json             purpose, targets, audience card (confirmed)
  01-sources/
    manifest.json
    raw/                     fetched / copied originals (read-only)
    normalized/*.md          with paragraph ids
    injection-scan.json
  02-rubric.json             locked after confirmation
  03-reviews/<model>/        round-1 outputs (JSON)
  04-debate/<model>.json     round-2 responses
  05-consensus.json
  factcheck/ledger.jsonl
  06-report.v1.md
  07-revision/A.diff  B.md  rereview.json
  08-decision.json
  style-guide-delta.md
```

## 6. Per-user store (never shipped)

The location comes from the platform's data directory, e.g. `~/.local/share/ant-peer-review/`.

```
config.toml                  lang, backend, reviewers
LESSONS.md                   index table (本檔 / 封存) + full text of 本檔 lessons
lessons/_archive.md          full text of every lesson, verbatim
lessons/.next_id             monotonic counter; ids never reused
site-profiles.json           per-domain crawl rules, applied by code
style-guides/<brand>.md
runs/
```

**Lessons**
- They cover how the tool should work: crawl incidents, decisions taken during runs.
- `ant-peer-review lessons new "<title>"` assigns the id: max(counter, highest id in the archive) + 1. It then asks for Cause / Rule / Enforced.
- Every new lesson adds an index row and appends its full text to `_archive.md`.
- Reading: scan the index first, and open the archive only for the areas being touched (crawl/<domain>, factcheck, rubric, …).
- Lessons drafted by the model from run content are shown to the user and written only after confirmation. When read back they are data, never instructions.
- When the same lesson recurs, it is promoted to a machine rule instead of more text:
  - crawl lessons go into `site-profiles.json`
  - wording lessons go into the Style Guide
  - decision lessons go into audience/rubric defaults

This store is separate from the repository's own development `LESSONS.md` (maintained with ant-mode's `ant record new lesson`). That file covers how this project is built; it is not shipped to users.

## 7. Backends and models

| Alias | Model id |
|---|---|
| opus | `claude-opus-5-5` |
| sonnet | `claude-sonnet-5-5` |
| fable | `claude-fable-5-1` |

**`claude-cli`**
- Runs `claude -p --model …` and validates the JSON against the schema, retrying on failure.
- Uses the user's Claude Code login and plan limits. There is no batch discount.

**`anthropic-api`**
- Uses the Anthropic SDK: structured outputs, server-side web search, prompt caching (the article + rubric prefix is shared by one model's calls), and the Batch API for fact-check backlogs.
- Effort is set explicitly to `high` or above (Opus 5.5 defaults to `medium`).
- `stop_reason: refusal` is handled and recorded.
- Credentials come from `ANTHROPIC_API_KEY` or Anthropic's own `ant auth login`. That is a different `ant` from ant-mode; the README must say so.

**Cost** (estimate, not measured; assumes ~3000-word article, ~15k input / 4k output tokens per call, ~7 calls per model):

| Backend | Reviewers | Cost per article |
|---|---|---|
| `anthropic-api` | opus + sonnet | ~US$2–4 |
| `anthropic-api` | with fable | ~US$5–10 |
| `claude-cli` | any | $0 marginal within plan limits |

To be replaced with measured numbers from the prototype.

## 8. Borrowed from reference skills

| Source | Taken | Left out |
|---|---|---|
| K-Dense-AI peer-review | 5-field comment schema + linter; claim–evidence support levels; exit codes 0/1/2; atomic no-overwrite writes; "orient without deciding" | "never score" rule; medical reporting guidelines |
| tsingke/thesis-review-skill | per-item folders + summary table; per-dimension score bands; cross-perspective consistency | persona scores as multiples of one score; boilerplate templates; 80-point floor; no HITL |
| jam-cc/paper-review.skill | identity / publication / support error classes; cascade deletion; evidence notes file; no issue quotas | prose-only style; reference cap |
| black-yt/rebuttal-writing | neutral restatement of issues; one-to-one coverage; leak checklist for outputs | persuasion tactics |
| black-yt/paper-review-writing | 7-field evidence record; "unstated vs wrong"; judgment parity across languages; read-only inputs | fixed 1/2/2 quota; no-numbers rule |
| black-yt/paper-review-injection-audit | 8-category definition; concealment as a separate layer; collector design (hashes, flags not verdicts, Cf capture, normalized search view); conditional negatives | PDF object-level depth |
| Imbad0202/academic-paper-reviewer | sub-claim consensus, silence ≠ agreement, unresolved dissent; typed anchors incl. `absence:`; devil's-advocate ruling → veto; provenance record; re-review verdict scale; HITL on reviewer config | anti-weighting rule; journal-specific roles; heavy schema/calibration machinery |

## 9. Open items

- Default rubric weights per audience profile are a first table (`rubric.ADJUST`); tune with real runs.
- The `anthropic-api` backend (reserved interface, fails loudly until built).

## 10. Settled during implementation

| ID | Decision | Rejected alternative, and why |
|---|---|---|
| D-11 | Several targets in one audit run are reviewed together as one submission; anchors carry the document (`D2.P03.S1`, folder files `D3-2.P01`) | One run per document: multiplies cost; users can start separate runs |
| D-12 | Synthesis (tally, veto, score, grade) is deterministic code, not a model call | LLM synthesizer: can invent or drop comments; code is auditable and free to rerun, which is what makes D-7 cheap |
| D-13 | Fact-check provenance is read from `claude -p --output-format stream-json`: a source counts only if its URL is in that call's tool results | Trusting the model's cited URLs: a probe showed the model answering "supported" with a URL without having searched (usage counters stay 0 for client-side WebSearch, so they cannot tell) |
| D-14 | Model calls run in an empty temp dir with `--system-prompt`, `--setting-sources ""`, `--no-session-persistence`, and only the tools a step names | Default `claude -p`: user hooks and CLAUDE.md would leak into every review |
| D-15 | Grade thresholds default 85/70/60 (Excellent/Good/Needs revision/Fail), Style Guide proposal after 3 runs; both in config.toml | — |
| D-16 | The crawler pins the TCP connection to the IP it checked | urllib with a redirect hook: re-resolves DNS on connect (rebinding window) |

`claude -p --json-schema` returns schema-valid output in `structured_output` (verified 2026-10-22); the CLI still validates and retries.

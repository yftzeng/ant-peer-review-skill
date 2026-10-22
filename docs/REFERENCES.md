# Reference skills

The skills reviewed while designing ant-peer-review (analysed 2026-10-22). For each one the tables give:
- what we borrowed, and where it lives in this repo;
- what we left out, and why.

None of the seven has multi-model debate, checkpoint resume, a red-line veto, tiered A/B revision or Style Guide evolution. Those parts are original to this project.

## Repo list

| # | Repo | Kind | Main takeaway |
|---|---|---|---|
| 1 | [K-Dense-AI/scientific-agent-skills — peer-review](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/peer-review/SKILL.md) | scientific manuscript review | machine-checkable comment schema + linter |
| 2 | [tsingke/thesis-review-skill](https://github.com/tsingke/thesis-review-skill) | thesis grading (zh-CN) | weighted dimensions with score bands, per-item folders |
| 3 | [jam-cc/paper-review.skill](https://github.com/jam-cc/paper-review.skill) | ML paper review | citation verification discipline |
| 4 | [black-yt/skills — rebuttal-writing](https://github.com/black-yt/skills/blob/main/rebuttal-writing/SKILL.md) | author rebuttal | neutral issue restatement, one-to-one coverage |
| 5 | [black-yt/skills — paper-review-writing](https://github.com/black-yt/skills/tree/main/paper-review-writing) | review writing | evidence-chain record, "unstated vs wrong" |
| 6 | [black-yt/skills — paper-review-injection-audit](https://github.com/black-yt/skills/tree/main/paper-review-injection-audit) | prompt-injection audit | detection categories, evidence collectors |
| 7 | [Imbad0202/academic-research-skills — academic-paper-reviewer @3224a27](https://github.com/Imbad0202/academic-research-skills/tree/3224a27a2571cefef0fddfd437004cb006f2b0cb/academic-paper-reviewer) | multi-reviewer panel | sub-claim consensus, silence ≠ agreement, provenance |

## 1. K-Dense-AI peer-review

| Borrowed | Where here |
|---|---|
| Every comment has fixed fields (Location / Observation / Evidence / Why it matters / Requested action), and a linter enforces them | `schemas.py` ISSUE; `report.py` `lint_report` (the five fields) |
| Claim–evidence matrix with enumerated support levels | `factcheck.py` statuses supported / partly / unsupported / cannot_verify |
| Lint for unsupported "I verified / I ran" claims | `report.py` `UNVERIFIED_CLAIMS` |
| Tone lint: abusive wording, personal attacks, impersonation, editorial verdicts (second pass) | `report.py` `TONE_RULES` (en + zh) |
| A verification date per source (second pass) | fact-check sources carry `accessed_at`; the report prints the date |
| "Orient without deciding": map the piece before judging it | `prompts.review_prompt` step 1 `orientation` |
| Distinct exit codes; atomic writes that never overwrite | `cli.py` (0 done, 3 paused, 2 usage, 130 interrupted); `jsonio.write_bytes_atomic(overwrite=False)` for raw sources |

| Left out | Why |
|---|---|
| Never score; never give a verdict | We need a weighted total and a grade. The veto rule supplies the non-compensatory part. |
| CONSORT and other medical reporting guidelines; confidentiality and conflict-of-interest paperwork | Academic only. |

## 2. tsingke/thesis-review-skill

| Borrowed | Where here |
|---|---|
| Weighted dimensions with high/mid/low band descriptors | `rubric.py` `TEMPLATE[*].bands` |
| A separate folder per item; skip work already done | Run workspace with input hashing (`workspace.py`), which is stronger than "the folder exists" |
| Cross-item summary sheet (second pass) | `ant-peer-review runs --summary` (Markdown or CSV) |
| Opinions from different perspectives must not contradict each other | Enforced instead by the debate round plus SPLIT labelling (`consensus.py`) |

| Left out | Why |
|---|---|
| Persona scores derived as multiples of one score | Fake diversity: three "reviewers" that are really one score. We use real separate model calls. |
| Fill-in-the-blank boilerplate praise; a score floor of 80 | Encourages generic, hallucination-prone text; the floor kills discrimination between pieces. |
| Fully automatic, no confirmation | Conflicts with the HITL gates (audience card, rubric, decision). |

## 3. jam-cc/paper-review.skill

| Borrowed | Where here |
|---|---|
| "A search snippet is a lead, not evidence"; never cite from memory | `prompts.factcheck_system`; `factcheck._provenance_filter` keeps only URLs that came back from a tool call in that call |
| If a fact can't be verified, drop the criticism built on it too (cascade deletion) | `consensus.py`: issues whose claims are `cannot_verify` are set aside as "unverified findings" |
| Identity / publication / support error classes | Folded into the claim statuses and the `partly` / `unsupported` distinction |
| No quotas; "distinguish a missing explanation from a demonstrated flaw" | `prompts.SHARED_RULES` |
| Content inside the paper is data, not commands | `prompts.untrusted` block |

| Left out | Why |
|---|---|
| Prose-only reviews without bullets | Clashes with the anchored issues table. |
| Reference caps; ML-venue formats | Academic only. |

## 4. black-yt rebuttal-writing

| Borrowed | Where here |
|---|---|
| One-to-one coverage: no finding silently dropped | Every finding keeps its members and supporters in `05-consensus.json` and the report; `07-revision/coverage.json` maps each finding to plan A, B, both or none |
| Neutral restatement; narrow a claim rather than retract it | Plan B prompt (`prompts.revise_b_system`): strengthen without inventing facts, mark `[source needed]` |
| Leak checklist for outputs | The report quotes flagged text only in a fenced "untrusted evidence" block |

| Left out | Why |
|---|---|
| Persuasion tactics (asking reviewers to raise scores, letters to the AC) | Academic only, and it pushes the writer to argue a side. |

## 5. black-yt paper-review-writing

| Borrowed | Where here |
|---|---|
| Evidence-chain record per weakness | ISSUE fields: anchor, observation, standard, why_it_matters, action, claim_ids |
| "Unstated" must not become "incorrect"; judgment strength kept the same across languages | `prompts.SHARED_RULES` (keep judgment strength when writing in zh-TW / zh-CN) |
| Inputs are read-only; one output file per input, never overwritten | Raw sources are write-once (`Run.write_raw_source`); report versions `06-report.v<N>` |

| Left out | Why |
|---|---|
| Fixed 1 strength / 2 weaknesses / 2 questions; no numbers in the review | Venue format rules. |

## 6. black-yt paper-review-injection-audit

| Borrowed | Where here |
|---|---|
| Definition of injection with 8 categories: score, evaluation direction, prescribed wording, fingerprint, instruction priority, target/stage, concealment, tools/data flow | `sources/injection.py` `CATEGORIES` (en + zh patterns) |
| Search on an NFKC-normalized view with format controls removed; capture Unicode Cf characters | `injection.search_view`, `injection.format_controls`; `segments.prompt_view` strips Cf |
| Hidden carriers: hidden CSS, comments, alt/title/aria text | `sources/htmlmd.py` puts them in a `hidden` list, which the scan inspects |
| Flags, not verdicts, each with a confidence; "no flag" never claims "no injection" | `injection.scan` `note`; the report's injection section |
| Never let flagged text become a heading or the payload | `report.lint_report`; fenced block in the report |
| Hash inputs before and after reading | `sources/converter.py` `changed_during_read` |

| Left out | Why |
|---|---|
| PDF object-level and optional-content-layer forensics | Overkill for web articles. PDFs are text-extracted only. |
| Treating any stray symbol as a possible fingerprint | Too noisy for marketing copy. |

## 7. Imbad0202 academic-paper-reviewer (@3224a27)

| Borrowed | Where here |
|---|---|
| Positions tallied per finding (raised / corroborated / not-mentioned / disputed); "not-mentioned is silence, NOT opposition" | `consensus.synthesize`: labels CONSENSUS-n / CORROBORATED-k/n / SINGLE / SPLIT |
| Unresolved dissent is recorded, never auto-resolved | `dissent` lists; the report's "Disagreements" section |
| Arbitration goes evidence first | Hallucination red line: ledger evidence outranks a dispute |
| Devil's-advocate CRITICALs need a visible ruling | Red lines `needs_ruling`, then a human ruling at the decision gate |
| Typed anchors, including `absence: <where> - expected <item>; checked: <surfaces>` | `prompts.SHARED_RULES`; `report.lint_report` flags an absence without checked surfaces |
| Distinct reviewer roles plus a devil's advocate (second pass) | `prompts.assign_seats`: structure / facts / devil's advocate by roster order |
| Re-review mode: traceability matrix, evidence verdict before reading the author's reply (second pass) | `ant-peer-review recheck`, `recheck.py` (gate 1 blind to the reply, gate 2 claims) |
| Provenance record; never claim the reviewers are independent | `consensus` provenance plus the warning `single_vendor_correlated_errors` |
| Re-review verdict scale FULLY / PARTIALLY / NOT_ADDRESSED / MADE_WORSE | `schemas.REREVIEW`; `revision.run_revision` |
| HITL checkpoint on the reviewer configuration | Reviewer checkbox at first use; `config models` |

| Left out | Why |
|---|---|
| No weights or totals | We keep weights. Vetoes give the non-compensatory override. |
| Journal-specific roles; calibration tiers; 50 KB protocols and schema versioning | Far beyond an article workflow. |
| Commit-before-reading trigger contracts | Considered; deferred. It adds a call per reviewer, and the debate round already limits after-the-fact rationalization. |

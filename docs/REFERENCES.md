# References

Everything ant-peer-review draws on, analysed 2026-10-22. Two kinds:
- **Reference skills (§1–§5)**: other review skills, all MIT. Each section lists what we borrowed, where it lives in this repo, and what we left out and why.
- **Independent sources (§6)**: standards, papers and handbooks. They replace four skills whose licences do not allow commercial use (repo list rows 6–9); every idea first seen there is traced here to a public source, and their terms are not used.

None of the skills has multi-model debate, checkpoint resume, a red-line veto, tiered A/B revision or Style Guide evolution. Those parts are original to this project.

## Licences

This repo copies no code, prompts or text from any of these skills; it takes only ideas and methods, written anew here. Licences as checked on 2026-10-22 (LICENSE file, GitHub API and SKILL.md frontmatter):

| # | Licence | Commercial use |
|---|---|---|
| 1, 4, 5 (K-Dense-AI) | MIT (repo and each skill's frontmatter) | yes |
| 2 (tsingke) | MIT | yes |
| 3 (jam-cc) | MIT | yes |
| 6, 7, 8 (black-yt) | none stated (no LICENSE file; all rights reserved by default) | no: superseded by §6, nothing copied |
| 9 (Imbad0202 @3224a27) | CC BY-NC 4.0 | no: superseded by §6, nothing copied |

Do not paste text or code from rows marked "no" into this repo.

## Repo list

| # | Repo | Kind | Licence | Main takeaway |
|---|---|---|---|---|
| 1 | [K-Dense-AI/scientific-agent-skills — peer-review](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/peer-review/SKILL.md) | scientific manuscript review | MIT | machine-checkable comment schema + linter |
| 2 | [tsingke/thesis-review-skill](https://github.com/tsingke/thesis-review-skill) | thesis grading (zh-CN) | MIT | weighted dimensions with score bands, per-item folders |
| 3 | [jam-cc/paper-review.skill](https://github.com/jam-cc/paper-review.skill) | ML paper review | MIT | citation verification discipline |
| 4 | [K-Dense-AI/scientific-agent-skills — paperzilla](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/paperzilla/SKILL.md) | CLI wrapper for a paper-recommendation service | MIT | label what a summary was built from; keep tokens out of logs; honest paging |
| 5 | [K-Dense-AI/scientific-agent-skills — paper-lookup](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/paper-lookup/SKILL.md) | 18 scholarly APIs with provenance | MIT | "APIs can fail with HTTP 200"; identifier resolution; credential redaction; bounded work |
| 6 | [black-yt/skills — rebuttal-writing](https://github.com/black-yt/skills/blob/main/rebuttal-writing/SKILL.md) | author rebuttal | none | superseded by §6 |
| 7 | [black-yt/skills — paper-review-writing](https://github.com/black-yt/skills/tree/main/paper-review-writing) | review writing | none | superseded by §6 |
| 8 | [black-yt/skills — paper-review-injection-audit](https://github.com/black-yt/skills/tree/main/paper-review-injection-audit) | prompt-injection audit | none | superseded by §6 |
| 9 | [Imbad0202/academic-research-skills — academic-paper-reviewer @3224a27](https://github.com/Imbad0202/academic-research-skills/tree/3224a27a2571cefef0fddfd437004cb006f2b0cb/academic-paper-reviewer) | multi-reviewer panel | CC BY-NC 4.0 | superseded by §6 |

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

## 4. K-Dense-AI paperzilla

| Borrowed | Where here |
|---|---|
| Label whether a summary used metadata, an abstract or the full text | Report "Sources" section: page / feed copy (may be lossy) / file / pasted text, plus failed targets |
| Access errors are not an empty result | 200 pages that are challenges, soft 404s, login or paywalls fail with that reason (`sources/quality.py`) |
| Feed tokens stay out of logs and reports | `sources/urls.redact`: credential-like query values masked as REDACTED |
| Report partial pages honestly | The feed picker says a feed may list only its latest items |

| Left out | Why |
|---|---|
| The `pz` CLI, account login, recommendation feedback | Specific to that service. |

## 5. K-Dense-AI paper-lookup

| Borrowed | Where here |
|---|---|
| "These APIs can fail with HTTP 200": check the shape, not the status | Page quality checks; arXiv "not found" is an empty feed or an "Error" entry, both handled |
| Resolve identifiers against authoritative sources; check retraction notices | Opt-in `--academic` / checkbox: DOIs via doi.org + Crossref (`updated-by` retraction), arXiv ids via the export API (`scholarly.py`) |
| Redact credentials in recorded URLs | `sources/urls.redact` |
| Bound total work; rate-limit per host | Confirm before more than 3 feed runs; 1 s per host, 3 s for arXiv |

| Left out | Why |
|---|---|
| The other 15 databases (PubMed, bioRxiv, PubTator, ...) | Biomedical research retrieval, not article review. |
| API keys and `.env` loading rules | No keys are used. |
| The closing request to cite the authors' paper | An instruction inside third-party content; treated as data, not followed. |

## 6. Independent sources (replace rows 6–9)

Rows 6–9 of the repo list were read during design. On the licence review (2026-10-22) every idea taken from them was traced to an independent, public source below, and the terms they used were renamed. The code, prompts and docs now follow these sources; nothing from rows 6–9 remains.

| Concept | Independent source | Where here |
|---|---|---|
| Tally each finding per reviewer; a silent reviewer has not agreed; an objection is addressed, never outvoted; dissent is recorded | P. Resnick, [RFC 7282: On Consensus and Humming in the IETF](https://www.rfc-editor.org/rfc/rfc7282.html) (2014) | Debate positions `support` / `object`; `consensus.synthesize` labels CONSENSUS-n / SUPPORTED-k/n / SINGLE / SPLIT; `dissent` lists |
| Ledger evidence outranks an objection | K-Dense claim–evidence matrix (§1, MIT) | Hallucination red line in `consensus.synthesize` |
| A contested red line, and the reviewer roster, go to a human | NIST [AI RMF 1.0 (AI 100-1)](https://doi.org/10.6028/NIST.AI.100-1), human oversight | `needs_ruling` → decide gate; reviewer checkbox and `config models` |
| A missing item names what was searched; "not stated" is not "stated wrongly" | D. G. Altman & J. M. Bland, [Absence of evidence is not evidence of absence](https://pmc.ncbi.nlm.nih.gov/articles/PMC2550545/), BMJ 1995 | Anchor `missing: <where> - expected <item>; searched: <parts>`; `report.lint_report`; `prompts.SHARED_RULES` |
| Reviewers from one vendor share errors, so give them different lenses and never call them independent | E. Kim et al., [Correlated Errors in Large Language Models](https://arxiv.org/abs/2506.07962), ICML 2025; Y. Du et al., [Multiagent Debate](https://arxiv.org/abs/2305.14325), ICML 2024 | `prompts.assign_seats`; provenance warning `single_vendor_correlated_errors` |
| A skeptic seat reads against the grain | U.S. Government, [*A Tradecraft Primer: Structured Analytic Techniques*](https://www.cia.gov/resources/csi/books-monographs/a-tradecraft-primer) (2009), devil's advocacy; U.S. Army TRADOC, [*The Red Team Handbook* v9.0](https://home.army.mil/wood/6115/8222/0759/RedTeamHB.pdf); E. de Bono, *Six Thinking Hats* (1985), black hat | Seat `skeptic` |
| Judge a revision before reading the author's reply | [Cochrane Handbook, ch. 8](https://training.cochrane.org/handbook/current/chapter-08): bias in measurement of the outcome, blinding of outcome assessors | `recheck` gate 1 never sees the reply; gate 2 compares claims |
| Rate change since the earlier version, best to worst | Clinical Global Impression – Improvement scale (W. Guy, ECDEU Assessment Manual, 1976), change from baseline; see J. Busner & S. D. Targum, [Psychiatry (Edgmont) 2007](https://pmc.ncbi.nlm.nih.gov/articles/PMC2880930/) | `RESOLVED / IMPROVED / UNCHANGED / WORSE` (+ `CANNOT_VERIFY` in recheck) |
| Every finding is mapped to what handled it; none dropped silently | Bidirectional traceability matrix ([NASA SWE-059](https://swehb.nasa.gov/spaces/7150/pages/16449675/SWE-059+-+Bidirectional+Traceability+Between+Software+Requirements+and+Software+Design)); W. S. Noble, [Ten simple rules for writing a response to reviewers](https://doi.org/10.1371/journal.pcbi.1005730), PLOS Comput Biol 2017 | `07-revision/coverage.json`; findings keep members and supporters |
| Restate neutrally; narrow a claim instead of inventing support | Noble 2017 (above) | Plan B prompt: `[source needed]` |
| Each finding carries claim, grounds and why it matters | S. Toulmin, [*The Uses of Argument*](https://doi.org/10.1017/CBO9780511840005) (1958); K-Dense five fields (§1, MIT) | ISSUE fields anchor / observation / standard / why_it_matters / action |
| The same judgment strength in every output language | D. Wild et al., [ISPOR principles for translation and cultural adaptation](https://doi.org/10.1111/j.1524-4733.2005.08203.x), Value in Health 2005 (conceptual equivalence) | `prompts.SHARED_RULES` |
| Inputs are never modified; outputs are versioned | [NIST SP 800-86](https://doi.org/10.6028/NIST.SP.800-86), *Guide to Integrating Forensic Techniques into Incident Response* (2006) | `Run.write_raw_source` write-once; `06-report.v<N>` |
| Injection categories | [OWASP LLM01:2025 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/); K. Greshake et al., [indirect prompt injection](https://arxiv.org/abs/2302.12173), AISec 2023; Z. Lin, [hidden prompts in manuscripts](https://arxiv.org/abs/2507.06185), 2025; [Publish to Perish](https://arxiv.org/abs/2508.20863), 2025 | `injection.CATEGORIES`: rating_manipulation, sentiment_steering, output_dictation, canary_check, instruction_override, addressed_to_ai, secrecy_request, action_request |
| Search a normalized view; catch invisible and bidi characters | Unicode [UAX #15](https://www.unicode.org/reports/tr15/) (NFKC), [UTS #39](https://www.unicode.org/reports/tr39/); N. Boucher & R. Anderson, [Trojan Source](https://arxiv.org/abs/2111.00169) (CVE-2021-42574) | `injection.search_view`, `format_controls`; `segments.prompt_view` |
| Hidden carriers: hidden CSS, comments, alt / title / aria | Greshake et al. 2023; the 2025 white-text prompts in preprints (Lin 2025) | `htmlmd.py` `hidden` list |
| Flags are not verdicts; no flag does not mean no injection | OWASP LLM01:2025 (no fool-proof prevention); Altman & Bland 1995 | `injection.scan` note; report injection section |
| Flagged text never becomes a heading or reaches output unfenced | [OWASP LLM05:2025 Improper Output Handling](https://genai.owasp.org/llmrisk/llm052025-improper-output-handling/) | `report.lint_report`; fenced untrusted-evidence block |
| Hash an input before and after reading it | MITRE [CWE-367](https://cwe.mitre.org/data/definitions/367.html) (time-of-check / time-of-use) | `converter.changed_during_read` |

Left out (our own reasons, not inherited): persuasion tactics aimed at reviewers; fixed strength / weakness quotas; PDF object-level forensics; a no-weights rule; journal-specific roles and calibration tiers.

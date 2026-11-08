# D-0002 Long targets are reviewed map-reduce: parts, then one series-level pass

| | |
|---|---|
| Status | accepted |
| Decided | 2026-11-09 |
| Features | review-panel |
| Glossary term | |
| Authority | user, 2026-11-09: "一篇太大時，應該都可以參考 map reduce or divide and conquer", then "開工" to the proposed thresholds |
| Guard | tests/test_mapreduce.py (S-review-panel-031..033) |
| Migration | none: runs reviewed before keep their single-call records; a resumed review of a long target uses parts |
| Related | S-source-acquisition-054 (one document per article of a series); S-review-panel-027 (unreviewable) |

## Decision

A target of more than 80,000 characters, or one a reviewer refused as a whole, is reviewed in parts:

1. Divide: a series is grouped 5 articles to a part; a single long document is cut at its headings, about 30,000 characters a part. Anchors keep their ids.
2. Map: each reviewer reviews each part on its own. A refused part of several articles is retried one article at a time; an article still refused is skipped and listed.
3. Reduce: each reviewer makes one series-level call that sees the parts' maps and issues, not the text: the macro (structure) score, cross-part issues, and the whole's orientation. Code merges the rest: other dimensions are the parts' scores weighted by characters; issues, claims and red lines are joined with part-prefixed ids. The fact-check, debate and consensus then run as before; the debate sees only the paragraphs the findings point to.
4. When more than half of a reviewer's characters were skipped, that reviewer counts as refused. Otherwise the grade stands, marked provisional, and the report lists every unreviewed article.

## Why not the alternative

- One call for any size: a single refusal lost a whole 30-article series (four runs, $42), and long middles get less attention.
- Retrying every article alone on refusal: 60 calls for a 30-article series, with the rubric and instructions sent each time.
- Code averaging every dimension, macro included: structure across articles is exactly what no part can see.

## Deliberately not done

- Map-reduce for every target: a short piece gains nothing from parts and would pay for the extra series-level call. A single call did review a 200,000-character series without truncation (user feedback I4); the threshold sits lower for the refusal risk and the attention a long middle gets, as the user agreed.
- Overlap between parts: anchors would be cited twice and findings duplicated.

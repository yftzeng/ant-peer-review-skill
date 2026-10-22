# Feature: recheck

After an author revises a piece, `ant-peer-review recheck <run> --target <revised>`
checks the revision against the previous run's findings. The new run is linked
to the old one and keeps its reviewers, audience and rubric so the scores stay
comparable. Gate 1 judges every earlier finding from the revised text alone,
without the author's response; gate 2 (only with `--response`) then compares
what the author claims with those verdicts. The revised piece is also reviewed
in full, so new problems surface.

```gherkin
Feature: recheck
  @S-recheck-001
  Scenario: a recheck run is linked to its parent and keeps its yardstick
    Given a finished run P with reviewers opus and sonnet, an audience and an edited rubric
    When  "ant-peer-review recheck P --target revised.md --yes" runs
    Then  a new run records parent P, uses opus and sonnet, the same audience and a copy of P's rubric, and never asks about weights

  @S-recheck-002
  Scenario: gate 1 judges each earlier finding from the revised text, blind to the author's response
    Given P has findings F01 and F02 and the author's response says "F01 fixed"
    When  the recheck phase runs
    Then  each reviewer's gate-1 prompt lists F01 and F02 and the revised text
    And   no gate-1 prompt contains the author's response

  @S-recheck-003
  Scenario: gate 2 flags claims the evidence does not support
    Given gate-1 verdicts F01 UNCHANGED and F02 RESOLVED, and a response claiming both are fixed
    When  gate 2 runs
    Then  F01 is marked claim_supported false and F02 true
    And   without a response there is no gate-2 call

  @S-recheck-004
  Scenario: verdicts merge by majority, ties go to the less favourable verdict
    Given three reviewers judge F01 RESOLVED, RESOLVED, IMPROVED and F02 RESOLVED, UNCHANGED, CANNOT_VERIFY
    When  the verdicts merge
    Then  F01 is RESOLVED with agreement "majority" and F02 is UNCHANGED with agreement "split"

  @S-recheck-005
  Scenario: the report carries the revision check table next to the new review
    When  the recheck run's report is written
    Then  it has a section comparing against the parent report with one row per earlier finding and its verdict

  @S-recheck-006
  Scenario: runs created before the recheck phase existed stay finished
    Given a state.json from an older version without a "recheck" phase, every phase done
    When  it is loaded
    Then  the run is finished

  @S-recheck-007
  Scenario: verdicts written with the old scale are read with the new names
    Given stored gate-1 verdicts FULLY, PARTIALLY, NOT_ADDRESSED and MADE_WORSE from an older version
    When  the verdicts merge
    Then  they count as RESOLVED, IMPROVED, UNCHANGED and WORSE
```

## Must NOT
- @N-recheck-001 the author's response reaches a gate-1 prompt

## Revisions
- 2026-10-22 · +S-recheck-001..006 +N-recheck-001 · decision: none -- re-evaluated references: Imbad re-review mode (traceability matrix, evidence verdict before reading the author's response)
- 2026-10-22 · ~S-recheck-002..004 +S-recheck-007 · decision: none -- user: replace concepts and terms taken from CC BY-NC / unlicensed references with independently sourced ones (see docs/REFERENCES.md); scale renamed RESOLVED / IMPROVED / UNCHANGED / WORSE after the CGI-I change-from-baseline idea

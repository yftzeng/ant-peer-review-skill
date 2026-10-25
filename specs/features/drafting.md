# Feature: drafting

With purpose "drafting" the targets are materials: the first reviewer writes a
draft from them (facts only from the materials), the panel reviews the draft,
and while the grade is below Good the findings go back as feedback for one more
round, at most two rounds.

```gherkin
Feature: drafting
  @S-drafting-001
  Scenario: the draft, not the materials, is reviewed
    Given purpose "drafting" and a material "Fact A. Fact B."
    When  the run reaches review
    Then  01-sources/draft.v1.md exists and the review prompt holds the draft text, not "Fact B."

  @S-drafting-002
  Scenario: a weak draft is rewritten once with the findings as feedback
    Given every review scores 50
    When  the run completes
    Then  draft.v2.md exists, its prompt contained the round-1 findings, and no draft.v3.md exists

  @S-drafting-003
  Scenario: a good first draft is not rewritten
    Given every review scores 90
    When  the run completes
    Then  only draft.v1.md exists

  @S-drafting-004
  Scenario: a figure the materials do not hold is caught in code
    Given the material "Revenue was 12 million in 2025." and a first draft saying "Revenue was 15 million in 2025."
    When  the draft is reviewed
    Then  it is rewritten once even with a good grade, and the rewrite prompt names "15" as a figure the materials do not hold
    And   review.md's check table has the row "figures not in the materials", failing with "15" while a draft still has one and passing once every figure appears in the materials; an audit run has no such row
```

## Must NOT
- @N-drafting-001 materials text flagged as injection reaches the draft prompt

## Revisions
- 2026-10-22 · +S-drafting-001..003 +N-drafting-001 · decision: none -- follows docs/DESIGN.md §3 Drafting mode
- 2026-10-26 · +S-drafting-004 · decision: none -- user: 開工 (port from ant-pr-review: a draft may not carry a figure the materials do not hold, checked in code instead of the prompt alone)

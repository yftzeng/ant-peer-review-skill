# Feature: revision

Two revision tiers from the consensus findings: A (line edit) keeps the
structure and outputs a character-level diff that works for CJK text; B
(developmental edit) rewrites flagged paragraphs, proposes headlines and cites
the issues each change addresses, then a second model re-reviews B.

```gherkin
Feature: revision
  @S-revision-001
  Scenario: the A diff marks changes character by character
    Given paragraph D1.P02 "我們的產品很棒棒，大家都喜翻。"
    When  plan A returns "我們的產品很棒，大家都喜歡。"
    Then  A.diff shows "@@ D1.P02 @@" with "很棒[-棒-]" and "喜[-翻-]{+歡+}"
    And   A.md holds the full revised text with unchanged paragraphs kept

  @S-revision-002
  Scenario: plan A gets micro findings, plan B gets macro and meso findings
    Given findings F01 macro major, F02 meso major and F03 micro minor
    When  the revision phase runs
    Then  the A prompt lists F03 only and the B prompt lists F01 and F02

  @S-revision-003
  Scenario: B is re-reviewed by a different model with the four-level scale
    Given reviewers opus and sonnet and plan B written by opus
    When  the re-review runs
    Then  sonnet judges each addressed issue as FULLY, PARTIALLY, NOT_ADDRESSED or MADE_WORSE

  @S-revision-004
  Scenario: unknown paragraph ids from a model are ignored and reported
    Given plan A returns paragraph "D9.P99"
    When  the revision is applied
    Then  the text is unchanged for that id and a warning names "D9.P99"

  @S-revision-005
  Scenario: no macro or meso finding means no plan B call
    Given only micro findings
    When  the revision phase runs
    Then  B is skipped with a note and no B call is made
```

## Must NOT
- @N-revision-001 a heading or paragraph the model did not return is altered

## Revisions
- 2026-10-22 · +S-revision-001..005 +N-revision-001 · decision: none -- follows docs/DESIGN.md §3 P8

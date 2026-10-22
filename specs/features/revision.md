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
    Then  sonnet judges each addressed issue as RESOLVED, IMPROVED, UNCHANGED or WORSE

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

  @S-revision-006
  Scenario: sentence ids and inserted paragraphs from a model are applied
    Given paragraph D1.P02 with sentences S1 "Old one." and S2 "Keep two."
    When  plan B returns id "D1.P02.S1" with "New one." and id "D1.P02+" with "Inserted para."
    Then  D1.P02 reads "New one. Keep two." and "Inserted para." follows it as its own paragraph

  @S-revision-007
  Scenario: a coverage table shows which plan handles each finding
    Given findings F01 (macro), F02 (micro) and F03 (micro), plan A changing F02's paragraph and plan B addressing F01
    When  the revision phase ends
    Then  07-revision/coverage.json maps F01 to B, F02 to A and F03 to none, and the counts are printed
```

## Must NOT
- @N-revision-001 a heading or paragraph the model did not return is altered

## Revisions
- 2026-10-22 · +S-revision-001..005 +N-revision-001 · decision: none -- follows docs/DESIGN.md §3 P8
- 2026-10-22 · +S-revision-006 · decision: none -- live run: models returned sentence ids and new paragraphs, which were dropped
- 2026-10-22 · +S-revision-007 · decision: none -- re-evaluated references: black-yt rebuttal one-to-one coverage, no finding silently dropped
- 2026-10-22 · ~S-revision-003 · decision: none -- user: replace concepts and terms taken from CC BY-NC / unlicensed references with independently sourced ones (see docs/REFERENCES.md)

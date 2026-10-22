# Feature: rubric

Proposes scoring dimensions and weights from the default template and the
audience card, lets the user confirm or edit them (custom dimensions allowed),
and locks the result. Includes the S-curve stage x audience fit table used by
the Impact dimension.

```gherkin
Feature: rubric
  @S-rubric-001
  Scenario: the default template has four dimensions summing to 100
    Given an audience with every layer skipped
    When  weights are proposed
    Then  the dimensions are macro 30, accuracy 30, micro 20, impact 20

  @S-rubric-002
  Scenario: the audience shifts the weights
    Given an audience with expertise "scholar"
    When  weights are proposed
    Then  accuracy weighs more than 30, the total is 100 and no weight is below 5

  @S-rubric-003
  Scenario: the user edits a weight and the rest is renormalized to 100
    Given the proposed rubric
    When  the user sets impact to 40 and confirms
    Then  impact is 40 and the four weights sum to 100

  @S-rubric-004
  Scenario: a custom dimension can be added
    When  the user adds dimension "brand voice" with weight 10
    Then  the rubric has five dimensions summing to 100, one keyed "custom-brand-voice"

  @S-rubric-005
  Scenario: S-curve fit follows the stage x audience table
    Given stage "startup"
    Then  the fit for expertise "scholar" with purpose "trend" is above 50
    And   the fit for expertise "public" with purpose "emotional" is below 50

  @S-rubric-006
  Scenario: an unverified S-curve stage is not scored and its weight goes back to Impact
    Given reviewers' impact score 80 and an S-curve fit of 20
    When  the stage is "cannot_verify"
    Then  the final impact score is 80
    And   with a verified stage it is 0.75 x 80 + 0.25 x 20 = 65

  @S-rubric-007
  Scenario: several values in one audience layer average their weight shifts
    Given an audience with expertise ["scholar", "public"]
    When  weights are proposed
    Then  each dimension shifts by the mean of the scholar and public shifts, and the total is 100

  @S-rubric-008
  Scenario: S-curve fit with several audience values uses the share of good and poor matches
    Given stage "startup" and expertise ["scholar", "public"] with purpose ["trend"]
    Then  the fit is 50 + 50 x (2 good - 1 poor) / 3 values = 66.7
```

## Must NOT
- @N-rubric-001 a locked rubric whose weights do not sum to 100

## Revisions
- 2026-10-22 · +S-rubric-001..006 +N-rubric-001 · decision: none -- follows docs/DESIGN.md §3 P5
- 2026-10-22 · +S-rubric-007 +S-rubric-008 · decision: none -- multi-select audience: shifts are averaged per layer, fit is a share so it cannot run away with many ticks

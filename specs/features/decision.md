# Feature: decision

The human gate: contested red lines are ruled on, then the editor adopts plan
A, plan B or a manual edit, which becomes final.md. Corrections that keep
recurring for a brand are proposed for its Style Guide and written only after
confirmation.

```gherkin
Feature: decision
  @S-decision-001
  Scenario: contested red lines are ruled before choosing a plan
    Given red line "pr_landmine" needs a ruling
    When  the editor dismisses it
    Then  08-decision.json records the ruling and a new report version shows "Dismissed"

  @S-decision-002
  Scenario: the chosen plan becomes final.md
    Given plans A and B exist
    When  the editor chooses B
    Then  final.md equals B.md and 08-decision.json records choice "B"

  @S-decision-003
  Scenario: a recurring correction is proposed for the brand Style Guide
    Given brand "acme" and the correction "Acme Corp" -> "ACME" already seen twice in earlier runs
    When  this run makes the same correction and the editor confirms the proposal
    Then  style-guides/acme.md contains the rule "Acme Corp" -> "ACME"

  @S-decision-004
  Scenario: declining the proposal writes nothing
    Given the same recurring correction
    When  the editor declines
    Then  style-guides/acme.md does not exist

  @S-decision-005
  Scenario: non-interactive decision from arguments
    When  decide runs with --choice A --rule pr_landmine=confirmed
    Then  the ruling and choice are recorded without prompts

  @S-decision-006
  Scenario: a correction with a newline cannot add extra Style Guide lines
    Given a recurring correction from "Acme" to "ACME\n- \"x\" -> \"injected\""
    When  it is written to the Style Guide
    Then  the guide gains exactly one rule line
```

## Must NOT
- @N-decision-001 the Style Guide is written without the editor's confirmation

## Revisions
- 2026-10-22 · +S-decision-001..005 +N-decision-001 · decision: none -- follows docs/DESIGN.md §3 P9
- 2026-10-22 · +S-decision-006 · decision: none -- adversarial security review (sonnet) proved these by running

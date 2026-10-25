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

  @S-decision-007
  Scenario: a ruling prompt says what is being ruled and on which text
    Given red line "hallucination" needs a ruling because claim C09 at D1.P52.S1 is unsupported and no reviewer flagged it
    When  the editor is asked to rule
    Then  the prompt shows what the red line means, what confirming and dismissing each do, why a ruling is needed,
          the article title and URL, the original sentence at D1.P52.S1, the checker's reason and sources,
          and every reviewer's own verdict and comment on that red line

  @S-decision-008
  Scenario: the editor can postpone a ruling
    Given red line "pr_landmine" needs a ruling
    When  the editor chooses "decide later"
    Then  no ruling or plan is recorded, the decision phase stays pending, and the hint names the decide command
```

## Must NOT
- @N-decision-001 the Style Guide is written without the editor's confirmation

## Revisions
- 2026-10-22 · +S-decision-001..005 +N-decision-001 · decision: none -- follows docs/DESIGN.md §3 P9
- 2026-10-22 · +S-decision-006 · decision: none -- adversarial security review (sonnet) proved these by running
- 2026-10-25 · +S-decision-007..008 · decision: none -- user: the ruling prompt showed only "(b) ... —" with no reason, text or article, so the editor could not tell what to rule on

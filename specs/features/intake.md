# Feature: intake

Collects what a run is about: the purpose (drafting or audit), the targets
(URLs, local paths, pasted text, one per line until the end key), and the
audience in five layers, each a checkbox: any number of options plus custom
values, none ticked meaning skip. The audience card is shown for confirmation or editing before the run
continues.

```gherkin
Feature: intake
  @S-intake-001
  Scenario: targets are classified and echoed until /done
    Given an existing folder "notes"
    When  the user enters "https://example.com/a", "notes", "Some pasted text" and "/done"
    Then  the targets are a url, a path and a text, each echoed with its number

  @S-intake-002
  Scenario: two empty lines or Ctrl-D also end the list
    When  the user enters "https://example.com/a", "", ""
    Then  the list ends with one target
    And   entering "https://example.com/a" then end-of-file also ends with one target

  @S-intake-003
  Scenario: consecutive text lines become one text target
    When  the user enters "Line one" and "Line two" and "/done"
    Then  there is one text target "Line one\nLine two"

  @S-intake-004
  Scenario: an empty target list asks again
    When  the user enters "/done" first, then "https://example.com/a" and "/done"
    Then  the user is told at least one target is needed and the final list has one url

  @S-intake-005
  Scenario: each audience layer is a checkbox with custom values; none ticked is skip
    When  the user ticks "expert" and "scholar" for layer a, ticks nothing for layer b, ticks "consumer" and adds custom "regulators" for layer c, and ticks one option each for d and e
    Then  the audience is {expertise: [expert, scholar], role: [], lens: [consumer, "custom:regulators"], trust: [stranger], purpose: [trend]}

  @S-intake-006
  Scenario: the audience card can be edited before confirming
    Given the audience card is shown with expertise ["expert"]
    When  the user chooses to edit layer a, ticks "beginner" too, then confirms
    Then  the saved audience has expertise ["beginner", "expert"]

  @S-intake-007
  Scenario: non-interactive intake from arguments
    When  intake is built from --purpose audit --target URL --target "text" --audience expertise=expert+scholar,purpose=trend
    Then  00-intake.json holds the same purpose, targets and audience (expertise [expert, scholar]) without any prompt

  @S-intake-008
  Scenario: an audience saved by an older version is read as lists
    Given 00-intake.json with audience {expertise: "expert", role: null}
    When  the audience is normalized
    Then  it reads {expertise: [expert], role: []}
```

## Must NOT
- @N-intake-001 an unknown audience key or option given on the command line is silently accepted

## Revisions
- 2026-10-22 · +S-intake-001..007 +N-intake-001 · decision: none -- follows docs/DESIGN.md §3 P1-P3
- 2026-10-22 · ~S-intake-005 ~S-intake-006 ~S-intake-007 +S-intake-008 · decision: none -- user request: every audience layer is a multi-select checkbox

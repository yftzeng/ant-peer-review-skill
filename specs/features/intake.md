# Feature: intake

Collects what a run is about: the purpose (drafting or audit), the targets
(URLs, local paths, pasted text, one per line until the end key), and the
audience in five layers, each answered with one option, a custom value or
skip. The audience card is shown for confirmation or editing before the run
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
  Scenario: each audience layer takes one option, a custom value or skip
    When  the user picks "expert" for layer a, skips layer b, enters custom "regulators" for layer c, picks options for d and e
    Then  the audience is {expertise: expert, role: null, lens: "custom:regulators", trust: ..., purpose: ...}

  @S-intake-006
  Scenario: the audience card can be edited before confirming
    Given the audience card is shown with expertise "expert"
    When  the user chooses to edit layer a and picks "beginner", then confirms
    Then  the saved audience has expertise "beginner"

  @S-intake-007
  Scenario: non-interactive intake from arguments
    When  intake is built from --purpose audit --target URL --target "text" --audience expertise=expert,purpose=trend
    Then  00-intake.json holds the same purpose, targets and audience without any prompt
```

## Must NOT
- @N-intake-001 an unknown audience key or option given on the command line is silently accepted

## Revisions
- 2026-10-22 · +S-intake-001..007 +N-intake-001 · decision: none -- follows docs/DESIGN.md §3 P1-P3

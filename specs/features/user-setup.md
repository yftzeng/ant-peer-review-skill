# Feature: user setup

On first use the CLI asks for the interface language, the backend and the
peer reviewer models (checkbox: opus and sonnet preselected, fable optional;
two or more recommended so they split the work and review each other, one
allowed after a warning), probes each chosen model, and saves the answers in the
per-user store. Every later run prints the active reviewers and the command
that changes them.

```gherkin
Feature: user setup
  @S-user-setup-001
  Scenario: first use preselects opus and sonnet
    Given no saved user config
    When  the reviewer checkbox is shown and the user just confirms
    Then  the saved reviewers are ["opus", "sonnet"]

  @S-user-setup-002
  Scenario: no reviewer at all is refused, and the minimum is checked only after confirming
    Given the reviewer checkbox, whose title recommends at least 2 models and states no minimum
    When  the user unticks every model and confirms
    Then  the user is told at least 1 reviewer is needed and the checkbox asks again

  @S-user-setup-003
  Scenario: every run prints the active reviewers and how to change them
    Given saved reviewers ["opus", "fable"] and language "en"
    When  a run starts
    Then  the output contains "Peer reviewers: opus, fable" and "ant-peer-review config models"

  @S-user-setup-004
  Scenario: config models re-shows the checkbox with the saved choice ticked
    Given saved reviewers ["opus", "fable"]
    When  the user runs "ant-peer-review config models" and ticks "sonnet" too
    Then  the saved reviewers are ["opus", "sonnet", "fable"]

  @S-user-setup-005
  Scenario: a model that fails its probe is not saved
    Given the backend probe fails for "fable"
    When  the user ticks opus, sonnet and fable and confirms
    Then  the user is told "fable" is unavailable and the saved reviewers are ["opus", "sonnet"]

  @S-user-setup-006
  Scenario: interface strings follow the chosen language
    Given language "zh-TW"
    When  the purpose question is shown
    Then  it is the zh-TW string, and every key in en exists in zh-TW and zh-CN

  @S-user-setup-007
  Scenario: a one-off override does not change the saved config
    Given saved reviewers ["opus", "sonnet"]
    When  a run starts with --models opus,fable
    Then  the run uses opus and fable and the saved reviewers are still ["opus", "sonnet"]

  @S-user-setup-008
  Scenario: questions, information and phases look different from each other
    Given output that is not a terminal
    When  a question, the reviewer banner and a phase start are printed
    Then  the question starts on a new block with "? ", the banner line starts with "ℹ " and puts the change hint on its own line, and the phase line is a "━━" rule
    And   no ANSI escape codes are printed

  @S-user-setup-009
  Scenario: a single reviewer is allowed after a warning
    Given the reviewer checkbox
    When  the user leaves only "opus" ticked and confirms
    Then  the user is told one reviewer means no peer review and a single opinion, and is asked to go on or choose again;
          going on saves ["opus"], choosing again re-shows the checkbox

  @S-user-setup-010
  Scenario: a one-off single-reviewer override runs with a warning
    When  a run starts with --models opus
    Then  the run uses ["opus"] and the banner warns that there is no peer review
```

## Must NOT
- @N-user-setup-001 the user store is written inside the installed skill directory

## Revisions
- 2026-10-22 · +S-user-setup-001..007 +N-user-setup-001 · decision: none -- first spec, decisions live in docs/DESIGN.md §1
- 2026-10-22 · +S-user-setup-008 · decision: none -- user: consecutive questions ran together and the reviewer banner looked like an answer
- 2026-10-25 · ~S-user-setup-002 +S-user-setup-009..010 · decision: none -- docs/DESIGN.md reviewer-roster row revised in place; user: at least 1 reviewer, checked after submit and not shown in the UI; the UI recommends 2 to split the work and cross-review

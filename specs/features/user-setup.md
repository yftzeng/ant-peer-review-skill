# Feature: user setup

On first use the CLI asks for the interface language, the backend and the
peer reviewer models (checkbox: opus and sonnet preselected, fable optional,
at least two), probes each chosen model, and saves the answers in the
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
  Scenario: fewer than two reviewers is refused
    Given the reviewer checkbox
    When  the user unticks "sonnet" leaving only "opus" and confirms
    Then  the checkbox explains that at least 2 reviewers are needed and asks again

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
```

## Must NOT
- @N-user-setup-001 the user store is written inside the installed skill directory

## Revisions
- 2026-10-22 · +S-user-setup-001..007 +N-user-setup-001 · decision: none -- first spec, decisions live in docs/DESIGN.md §1

# Feature: run workspace

Every review or drafting run lives in its own folder with a `state.json` that
records each phase's status and input hashes, so an interrupted run can be
resumed and a changed input re-runs exactly the phases downstream of it.
Editors running long reviews rely on it to never lose finished work.

```gherkin
Feature: run workspace
  @S-run-workspace-001
  Scenario: a new run gets its own folder and state
    Given an empty runs directory
    When  a run is created with slug "My Article!" at 2026-10-22 09:30
    Then  the folder "20261022-0930-my-article" exists
    And   its state.json lists every phase as "pending"

  @S-run-workspace-002
  Scenario: a finished phase with unchanged inputs is skipped on resume
    Given phase "rubric" is "done" with recorded input hashes
    And   the input files have the same sha256
    When  the run asks whether "rubric" must run
    Then  the answer is no

  @S-run-workspace-003
  Scenario: a changed input marks the phase and everything downstream stale
    Given phases "sources", "rubric" and "review" are "done"
    When  the content of an input of "rubric" changes
    Then  "rubric" and "review" are "stale" and "sources" stays "done"

  @S-run-workspace-004
  Scenario: rerun from a phase invalidates downstream phases
    Given phases "sources" to "report" are "done"
    When  the user reruns from "review"
    Then  "review" and every later phase are "stale"

  @S-run-workspace-005
  Scenario: unfinished runs are listed for resume
    Given one run with every phase done and one run whose "review" is pending
    When  unfinished runs are listed
    Then  only the second run is returned

  @S-run-workspace-006
  Scenario: writes are atomic and never overwrite a raw source
    Given a file already exists at a raw-source path
    When  the workspace is asked to write a raw source there again
    Then  the write is refused and the original bytes are unchanged
```

## Must NOT
- @N-run-workspace-001 a resumed run uses different reviewer models or backend than the ones recorded in its state.json

## Revisions
- 2026-10-22 · +S-run-workspace-001..006 +N-run-workspace-001 · decision: none -- first spec, decisions live in docs/DESIGN.md §1

# Feature: cli

The `ant-peer-review` command runs a whole review end to end, pauses cleanly
(awaiting a decision, a failed phase, Ctrl-C) and resumes from the first
unfinished phase. Every run prints the active reviewers first.

```gherkin
Feature: cli
  @S-cli-001
  Scenario: a non-interactive audit runs to the decision gate
    When  "ant-peer-review new --yes --backend fake --target <text>" runs
    Then  06-report.v1.md and 07-revision/A.md exist, the decision is pending
    And   the output contains "Peer reviewers: opus, sonnet" and the decide command

  @S-cli-002
  Scenario: resume skips finished phases and continues
    Given a run paused at the decision gate
    When  "ant-peer-review decide <run> --yes --choice A" runs, then "resume <run>"
    Then  final.md equals A.md, every phase is done and no reviewer model is called again

  @S-cli-003
  Scenario: rerun from review calls the reviewers again and writes a new report
    Given a finished run
    When  "ant-peer-review rerun <run> --from review --yes" runs
    Then  the review phase calls every reviewer again and report v2 is written

  @S-cli-004
  Scenario: an unfinished run is offered when starting interactively
    Given a run paused at the decision gate
    When  "ant-peer-review" starts interactively
    Then  the user is offered to continue that run from phase "decision"

  @S-cli-005
  Scenario: Ctrl-C during a phase leaves it resumable
    Given the backend raises KeyboardInterrupt during review
    When  the run is interrupted
    Then  the review phase is "pending", the exit code is 130 and the resume command is printed

  @S-cli-006
  Scenario: a backend failure pauses the run with a resume hint
    Given every reviewer fails with a backend error
    When  the run reaches review
    Then  the run pauses with exit code 3 and earlier phases stay done

  @S-cli-007
  Scenario: runs lists each run with its next phase
    Given one paused run
    When  "ant-peer-review runs" runs
    Then  the line for that run says "next: decision"

  @S-cli-008
  Scenario: the run folder is named after the target, not its full path
    When  runs start with targets "/tmp/x/my-article.md", "https://example.com/blog/hello-world" and text "# Big News\nBody"
    Then  the folder slugs are "my-article", "example-com-hello-world" and "big-news"

  @S-cli-009
  Scenario: leaving during interactive intake leaves no run folder
    Given no runs
    When  "ant-peer-review" starts interactively and the input ends while the audience is asked
    Then  the runs directory has no run in it

  @S-cli-010
  Scenario: an unfinished run can be deleted from the start menu, with confirmation
    Given an unfinished run "20261022-0923-run" holding only state.json
    When  the user picks "delete an unfinished run", chooses it, sees its file count and confirms
    Then  the folder is gone; declining the confirmation keeps it
```

## Must NOT
- @N-cli-001 a non-interactive run (--yes) waits for keyboard input

## Revisions
- 2026-10-22 · +S-cli-001..007 +N-cli-001 · decision: none -- follows docs/DESIGN.md §2
- 2026-10-22 · +S-cli-008 · decision: none -- live run: a path target produced a slug of the temp directory
- 2026-10-22 · +S-cli-009 +S-cli-010 · decision: none -- user saw an empty run left by an abandoned intake and stale dev runs in the start menu

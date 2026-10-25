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

  @S-cli-011
  Scenario: a feed URL lets the user tick articles, and each becomes its own run
    Given a feed with 3 articles
    When  "ant-peer-review" runs interactively with that URL and the user ticks articles 1 and 3
    Then  two runs are created, each holding one article, named after the article titles

  @S-cli-012
  Scenario: non-interactive feeds take the newest N articles
    When  "ant-peer-review new --yes --target <feed> --feed-limit 2" runs
    Then  two runs are created from the first two feed items

  @S-cli-013
  Scenario: a summary table compares every run
    Given two runs with reports (totals 74.3 and 61.0) and one run without a report
    When  "ant-peer-review runs --summary" runs, and again with "--format csv --out summary.csv"
    Then  the Markdown table has one row per run with title, total, grade, confirmed red lines, findings and next phase
    And   summary.csv holds the same rows with a header line

  @S-cli-014
  Scenario: the feed picker says a feed may list only its latest items
    Given a feed with 3 items
    When  the article checkbox is shown
    Then  its title says the feed lists 3 items and may show only the latest ones

  @S-cli-015
  Scenario: ticking more than 3 feed articles asks first, with the scale of the work
    Given a feed with 5 articles
    When  the user ticks all 5
    Then  they are told 5 runs with 2 reviewers each and asked to confirm, default no
    And   declining creates no run; confirming creates 5

  @S-cli-016
  Scenario: the feed picker lists articles oldest first and shows the counts and the page
    Given a feed of 12 articles, 11 dated and 1 undated, one of them reviewed in an earlier run
    When  the article checkbox is shown
    Then  dated articles come oldest first, the undated one last,
          and the status line shows 12 articles, 1 reviewed, and page 1/2

  @S-cli-017
  Scenario: an article reviewed before is marked but can be ticked again
    Given the article "Day 1 - Alpha" was reviewed in run R1 with total 61.8 and grade "revise"
    When  the article checkbox is shown and the user ticks it
    Then  its label says it was reviewed, with R1's date, total and grade,
          and a new run is created whose report says it re-reviews R1

  @S-cli-018
  Scenario: "more" goes straight to the article list of an earlier run's feed
    Given run R1 was created from a feed with purpose "audit", an audience card, brand "acme" and fact sources
    When  "ant-peer-review more R1" runs and the user ticks another article
    Then  no intake question is asked, and the new run has R1's purpose, audience, brand and fact sources
    And   "more" without a run uses the latest run made from a feed; a run not made from a feed is refused with a hint

  @S-cli-019
  Scenario: a finished feed run names the command for picking more articles
    Given a run made from a feed
    When  it finishes
    Then  the output names "ant-peer-review more <run>"
```

## Must NOT
- @N-cli-001 a non-interactive run (--yes) waits for keyboard input

## Revisions
- 2026-10-22 · +S-cli-001..007 +N-cli-001 · decision: none -- follows docs/DESIGN.md §2
- 2026-10-22 · +S-cli-008 · decision: none -- live run: a path target produced a slug of the temp directory
- 2026-10-22 · +S-cli-009 +S-cli-010 · decision: none -- user saw an empty run left by an abandoned intake and stale dev runs in the start menu
- 2026-10-22 · +S-cli-011..012 · decision: none -- user chose one run per ticked article (one report each) over one combined submission
- 2026-10-22 · +S-cli-013 · decision: none -- re-evaluated references: tsingke's cross-paper summary sheet; feeds now create one run per article
- 2026-10-22 · +S-cli-014 · decision: none -- paperzilla: report partial pages honestly; the iThome series feed lists 15 of its articles
- 2026-10-22 · +S-cli-015 · decision: none -- K-Dense paper-lookup: confirm a plan before work exceeds a bound; one run per article multiplies cost
- 2026-10-25 · +S-cli-016..019 · decision: none -- user: the article list is paged with counts, sorted oldest first; after a review the user can pick more articles without the intake questions, and an article reviewed before is marked but can be re-reviewed

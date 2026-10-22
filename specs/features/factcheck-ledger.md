# Feature: fact-check ledger

Claims extracted by the reviewers are merged into a per-run ledger and checked
with web search. A source counts only if it came back from an actual search or
fetch in that call. Unverifiable claims are recorded with a reason and the run
continues; `ant-peer-review factcheck <run> --continue` retries them later and,
when stopped, either saves for another time or finalizes: an unchanged ledger
keeps the report, a changed one produces the next report version with a
changelog, without new review calls.

```gherkin
Feature: fact-check ledger
  @S-factcheck-ledger-001
  Scenario: claims from several reviewers merge into one ledger
    Given opus and sonnet both extract "Revenue grew 40% in 2025" at D1.P02.S1, and sonnet also extracts a quote
    When  the ledger is built
    Then  it has 2 claims, the first extracted_by ["opus", "sonnet"], all "pending"

  @S-factcheck-ledger-002
  Scenario: a source that never came back from a search is dropped
    Given the checker returns "supported" with sources A and B, but only A appears in its search results
    When  the claim is checked
    Then  the claim keeps source A only

  @S-factcheck-ledger-003
  Scenario: no search at all means cannot_verify
    Given the checker answers "supported" without calling any search tool
    When  the claim is checked
    Then  its status is "cannot_verify" with reason "no_search"

  @S-factcheck-ledger-004
  Scenario: offline and timeout are recorded and retryable
    Given the backend fails with "offline" for claim C01 and "timeout" for C02
    When  the claims are checked
    Then  both are "cannot_verify" with those reasons and both count as retryable

  @S-factcheck-ledger-005
  Scenario: continue retries only pending and retryable claims
    Given C01 supported, C02 cannot_verify offline, C03 cannot_verify no_source
    When  factcheck --continue runs
    Then  only C02 is checked again

  @S-factcheck-ledger-006
  Scenario: an unfinished continue offers continue-later or finalize
    Given 18 of 30 claims done and 12 left (offline 9, timeout 3)
    When  the continue run stops
    Then  the summary shows "18/30" with the breakdown and offers the two choices

  @S-factcheck-ledger-007
  Scenario: finalize with no change keeps the report
    Given report v1 recorded ledger snapshot S and the ledger still hashes to S
    When  the user finalizes
    Then  the user is told the report is unchanged and no v2 is written

  @S-factcheck-ledger-008
  Scenario: finalize with changed facts writes the next version with a changelog
    Given report v1 recorded C02 as cannot_verify and it is now unsupported
    When  the user finalizes
    Then  06-report.v2.md exists, lists C02 "cannot_verify -> unsupported" and the red lines and scores it moved
    And   no reviewer model was called

  @S-factcheck-ledger-009
  Scenario: the S-curve stage becomes a ledger claim
    Given opus and sonnet both judge the stage "growth"
    When  the ledger is built
    Then  claim SC1 of type "s_curve_stage" states the growth stage

  @S-factcheck-ledger-010
  Scenario: partial, bare or input-only URLs never count as sources
    Given tool results containing only "https://real.example/page" and a search query containing "https://made.up/x"
    When  the checker cites "/", "https://real.example", "https://real.exam", "https://made.up/x" and "https://real.example/page/"
    Then  only "https://real.example/page/" is kept

  @S-factcheck-ledger-011
  Scenario: every kept source records when it was accessed
    When  a claim is checked and keeps a source
    Then  the source has an accessed_at timestamp and the report shows its date next to the URL
```

## Must NOT
- @N-factcheck-ledger-001 a claim is marked supported, partly or unsupported without at least one source that came back from a tool call

## Revisions
- 2026-10-22 · +S-factcheck-ledger-001..009 +N-factcheck-ledger-001 · decision: none -- follows docs/DESIGN.md §4
- 2026-10-22 · +S-factcheck-ledger-010 · decision: none -- adversarial security review (sonnet) proved these by running
- 2026-10-22 · +S-factcheck-ledger-011 · decision: none -- re-evaluated references: K-Dense source ledger keeps a verification date per source

# Feature: decision

The human gate: contested red lines are ruled on, then the editor adopts plan
A, plan B or a manual edit, which becomes audit.md (draft.md when drafting).
Three kinds of output close the run: that text, review.md (one complete
report: summary, key points and every check with its result and reason) and,
for an audit, one ready-to-send reply per chosen style (reply-<style>.md). Corrections that keep
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
  Scenario: the chosen plan becomes audit.md, or draft.md when drafting
    Given plans A and B exist
    When  the editor chooses B
    Then  audit.md equals B.md and 08-decision.json records choice "B" and that path
    And   for a drafting run the same file is draft.md

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

  @S-decision-009
  Scenario: review.md gathers every check into one report
    Given a run with a report, a fact-check ledger, an injection scan and plans A and B
    When  the plan is chosen
    Then  review.md has a verdict, a summary, key points that each cite finding ids, a checks table with one row per
          rubric dimension (score, pass / borderline / fail, the reviewers' reasons), one row per red line, and rows for
          the fact-check, the injection scan and the report lint, then the findings, the review process and where the detail files are

  @S-decision-010
  Scenario: the summary only keeps what the findings back
    Given the summary model returns a key point citing "F99", which does not exist, and one citing "F01"
    When  review.md is written
    Then  only the key point citing F01 is kept
    And   when the summary call fails, review.md is still written and says the summary is missing

  @S-decision-011
  Scenario: an audit ends with one reply per chosen style
    Given an audit run whose plan was just chosen
    When  the editor keeps all five styles ticked in the reply checkbox
    Then  reply-appreciative.md, reply-empathetic.md, reply-pragmatic.md, reply-socratic.md and reply-critical.md are written
          from one model call that is told to write in the article's language,
          with a length target per style that grows with the number and severity of findings
    And   unticking styles writes only the ticked ones; a drafting run asks nothing and writes no reply

  @S-decision-012
  Scenario: replies are chosen by argument when not interactive
    When  decide runs with --yes --choice A and then with --reply pragmatic,socratic, and with --reply none
    Then  the first writes all five replies, the second only those two, the third none

  @S-decision-013
  Scenario: a reply that attacks the author is flagged
    Given the reply model returns a critical reply containing "the author is clueless"
    When  the replies are written
    Then  the file is written with a warning at its top and the editor is told which style failed the tone check
```

## Must NOT
- @N-decision-001 the Style Guide is written without the editor's confirmation

## Revisions
- 2026-10-22 · +S-decision-001..005 +N-decision-001 · decision: none -- follows docs/DESIGN.md §3 P9
- 2026-10-22 · +S-decision-006 · decision: none -- adversarial security review (sonnet) proved these by running
- 2026-10-25 · +S-decision-007..008 · decision: none -- user: the ruling prompt showed only "(b) ... —" with no reason, text or article, so the editor could not tell what to rule on
- 2026-10-25 · ~S-decision-002 +S-decision-009..013 · decision: none -- user: end with audit (the best revision, like final), review (one detailed report with summary, key points and every check's score, result and reason) and reply files, one per style (appreciative, empathetic, pragmatic, socratic, critical), English names; drafting gets no reply

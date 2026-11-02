# Feature: writing gate

Text we generate for people to send (replies to an author, share posts)
must not read as machine-written. Every such text passes a gate: rule
checks that cost nothing (stock phrases, structure tells, platform limits,
an invented personal experience), then one judging call by a different
model. A hard failure is rewritten with its reasons, at most twice; what
still fails is written with a warning header, and every result is listed
in a checks file. Platform limits live in a data file the user can
override, with the date they were last checked and their sources.

```gherkin
Feature: writing gate
  @S-writing-gate-001
  Scenario: stock phrases fail the rule check unless the user allows them
    Given a zh-TW text containing "在這個快速變遷的時代" and "值得一提的是"
    When  the rule check runs
    Then  both are hard failures named "stock_phrase" with the phrase quoted
    And   with "值得一提的是" in the user's allow list only the first fails; a word in the deny list fails like a stock phrase

  @S-writing-gate-002
  Scenario: structural tells are soft warnings
    Given a text with 3 em dashes in 100 units, "不是…而是…" twice and 3 lines that start with an emoji, and a text of 4 paragraphs of equal length
    When  the rule check runs on each
    Then  "dashes", "not_but", "uniform_paragraphs" and "emoji_bullets" are soft warnings and nothing is a hard failure

  @S-writing-gate-003
  Scenario: an invented personal experience is a hard failure
    Given a text saying "我曾經在團隊裡導入過 K8s"
    When  the rule check runs with no user-supplied experience, and again with "我們去年把服務搬上 K8s"
    Then  the first is a hard failure "invented_experience" and the second passes

  @S-writing-gate-004
  Scenario: platform limits are counted the platform's way
    Given the platform file (X: 280 weighted, CJK 2, URL 23; Threads 500; Instagram 2,200 with at most 5 hashtags; LINE 5,000 UTF-16 units)
    When  150 Chinese characters, a space and one URL are checked for X, and a caption with 6 hashtags for Instagram
    Then  X counts 324 and fails "too_long"; Instagram fails "too_many_hashtags"
    And   a platforms.json in the user store overrides a value, e.g. X max 25,000 for a paid account

  @S-writing-gate-005
  Scenario: hard failures are rewritten at most twice, then marked
    Given a writer whose text keeps a stock phrase
    When  the gate runs
    Then  the writer is called with the failure reasons twice, the file is written with a warning header naming them,
          and the checks file lists every check with pass or fail and its reason

  @S-writing-gate-006
  Scenario: the judge is a different model and must quote its evidence
    Given reviewers opus and sonnet, and a judge verdict failing "filler" with the quoted sentence
    When  the gate judges a text written by opus
    Then  sonnet judges it, the failure counts as hard with that quote as the reason, and a failure without a quote is ignored

  @S-writing-gate-007
  Scenario: replies to the author pass the gate
    Given an audit run whose critical reply contains "總而言之"
    When  the replies are written
    Then  the reply is rewritten once without it and reply-checks.md lists each reply's checks

  @S-writing-gate-008
  Scenario: Chinese text with half-width punctuation is rewritten
    Given a text "K8s 入門系列,先會 Docker,再走四個階段:從部署到安全。"
    When  the rule check runs
    Then  it is a hard failure "halfwidth_punctuation"; a URL, "K8s" and "1,000" do not count
```

## Must NOT
- @N-writing-gate-001 a text that failed the gate is written without a warning header

## Revisions
- 2026-11-02 · created · decision: none -- no feature checks generated prose for machine-like writing: decision covers which outputs are written, review-panel checks the article, not our own text
- 2026-11-02 · +S-writing-gate-001..007 +N-writing-gate-001 · decision: none -- user: replies and share posts must lose the "AI taste" behind a checklist gate; platform limits checked on 2026-11-02 (sources in data/platforms.json)
- 2026-11-02 · +S-writing-gate-008 · decision: none -- live share run: zh-TW posts came back with ASCII commas and colons between Chinese characters

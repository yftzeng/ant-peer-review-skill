# Feature: output language

The user picks the languages the delivered text is written in (the adopted
article, replies, share posts), several at once, each with its regional
usage: English as written in the US, Traditional Chinese as used in Taiwan,
Simplified Chinese as used in mainland China. The default is the language
the command was run with. Usage is checked, not only asked for: the writing
gate fixes unambiguous regional terms and spellings and flags the rest.
Reports and checks files stay in the interface language, for the user.

```gherkin
Feature: output language
  @S-output-language-001
  Scenario: the interactive intake asks for the output languages after the content check
    Given the command was run with --lang zh-TW and the article is in English
    When  the user goes through the intake
    Then  after the content check a checkbox lists "English (US)", "繁體中文（台灣用語）", "简体中文（中国大陆用语）" in that order
          with 繁體中文 ticked, a note says the article is in English, at least one must stay ticked,
          and 00-intake.json holds output_langs ["zh-TW"] (or every ticked language, in menu order)

  @S-output-language-002
  Scenario: output languages from arguments
    When  "ant-peer-review new --yes --target <text> --lang en --output-lang zh-TW,en" runs
    Then  00-intake.json holds output_langs ["en", "zh-TW"]; without --output-lang it holds ["en"]
    And   "--output-lang fr" is refused with the allowed values

  @S-output-language-003
  Scenario: Taiwan usage: unambiguous mainland terms are replaced, ambiguous ones flagged, simplified characters must be fixed
    Given zh-TW text with "這個軟件的視頻", "這個項目" and "我们"
    When  the writing gate fixes and checks it for zh-TW
    Then  the fix-up writes "這個軟體的影片" and lists "軟件 → 軟體" and "視頻 → 影片" as changes
    And   "項目" is a weak tell "locale_term" suggesting 專案 (it can also mean "item"), "们" is a must-fix "script_mismatch",
          and a quoted 「軟件」 or a URL is left as written

  @S-output-language-004
  Scenario: mainland usage and US spelling are checked the same way
    Given zh-CN text with "这个软体" and "們", and en text with "the colour of organised centres" and a quoted "colour"
    When  the writing gate fixes and checks each
    Then  zh-CN becomes "这个软件" and "們" is a must-fix "script_mismatch"
    And   en becomes "the color of organized centers" while the quoted "colour" stays

  @S-output-language-005
  Scenario: replies and share posts are written once per output language
    Given an audit run with output languages zh-TW and en, and the reply style pragmatic
    When  the replies are written
    Then  one writing call per language writes reply-pragmatic.zh-TW.md and reply-pragmatic.en.md,
          each told its regional usage and passed through the gate with that language's rules,
          and reply-checks.md lists both; with a single output language the file is reply-pragmatic.md
    And   a share run writes share-x-summary.zh-TW.md and share-x-summary.en.md the same way

  @S-output-language-006
  Scenario: the adopted text is delivered in each output language
    Given an audit run of a zh-TW article that adopts plan A, with output languages zh-TW and en
    When  the decision is made
    Then  07-revision/adopted.md holds the adopted text, audit.zh-TW.md is that text with Taiwan usage fixed and no model call,
          audit.en.md is one localisation call into US English that passed the gate, and final-checks.md lists both
    And   with output language zh-TW only, audit.md is the adopted text with Taiwan usage fixed and nothing is localised

  @S-output-language-007
  Scenario: a drafting run writes its draft in the first output language
    Given a drafting run started with --lang en and --output-lang zh-TW
    When  the draft is written
    Then  the draft call is told to write in Traditional Chinese as used in Taiwan
```

## Must NOT
- @N-output-language-001 a regional fix-up changes text inside quotes, URLs or protected names (titles, authors)

## Revisions
- 2026-11-02 · created · decision: none -- intake asks the audience, writing-gate checks tells and decision adopts a plan; none says which language and regional usage the delivered text is in, and the user wants that chosen per run, several at once, with Taiwan and US usage checked
- 2026-11-02 · +S-output-language-001..007 +N-output-language-001 · decision: none -- user: a step in the interactive flow for the final output languages (English / 繁體中文 / 簡體中文, multi-select, default the --lang language), with Taiwan usage for 繁體中文 and US English for English

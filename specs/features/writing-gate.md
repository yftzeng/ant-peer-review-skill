# Feature: writing gate

Text we generate for people to send (replies to an author, share posts)
must not read as machine-written, and the gate edits it until it does not.
First a deterministic fix-up (punctuation, filler openers, Markdown,
hashtags, dashes); then rule checks and one judging call by a different
model sort what remains into must-fix, strong tells (one is enough) and
weak tells (two are needed); then an editing pass rewrites the text with
those reasons, keeping every supported claim and adding none, checked by
comparing the facts before and after; at most twice, then the fix-up
again. What still fails is written with a warning header, and the checks
file lists what was changed and what remains. Platform limits live in a data file the user can
override, with the date they were last checked and their sources.

```gherkin
Feature: writing gate
  @S-writing-gate-001
  Scenario: stock phrases are strong tells unless the user allows them
    Given a zh-TW text containing "在這個快速變遷的時代" and "值得一提的是"
    When  the rule check runs
    Then  both are strong tells named "stock_phrase" with the phrase quoted
    And   with "值得一提的是" in the user's allow list only the first fails; a word in the deny list fails like a stock phrase

  @S-writing-gate-002
  Scenario: structural tells are weak alone; a dash is a must-fix
    Given a text with 3 lines that start with an emoji, a text of 4 paragraphs of equal length, and a text with one "——"
    When  the rule check runs on each
    Then  "uniform_paragraphs" and "emoji_bullets" are weak tells and nothing else is; the dash is a must-fix "dashes",
          as is any "—", "–" or "―" outside quotes

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
  Scenario: a text is edited at most twice, then marked
    Given a writer whose text keeps a stock phrase the fix-up cannot remove
    When  the gate runs
    Then  the writer is called with the failure reasons twice, the file is written with a warning header naming them,
          and the checks file lists every check with pass or fail and its reason

  @S-writing-gate-006
  Scenario: the judge is a different model and must quote its evidence
    Given reviewers opus and sonnet, and a judge verdict failing "filler" with the quoted sentence
    When  the gate judges a text written by opus
    Then  sonnet judges it, the failure counts as a strong tell with that quote as the reason, and a failure without a quote is ignored

  @S-writing-gate-007
  Scenario: replies to the author pass the gate
    Given an audit run whose critical reply contains "說到底，問題在結構。"
    When  the replies are written
    Then  the reply is edited once without it and reply-checks.md lists each reply's checks

  @S-writing-gate-008
  Scenario: Chinese text with half-width punctuation is rewritten
    Given a text "K8s 入門系列,先會 Docker,再走四個階段:從部署到安全。"
    When  the rule check runs
    Then  it is a must-fix "halfwidth_punctuation"; a URL, "K8s" and "1,000" do not count

  @S-writing-gate-009
  Scenario: the fix-up changes what needs no judgment, and says so
    Given "值得一提的是，K8s 入門系列,先會 Docker。" and, for Instagram, "**重點** 好文 #a #b #c #d #e #f #g"
    When  the fix-up runs
    Then  the first becomes "K8s 入門系列，先會 Docker。" and the second "重點 好文 #a #b #c #d #e"
    And   "了」?" becomes "了」？" and "自動化(服務發現、Helm)" becomes "自動化（服務發現、Helm）", while "API (v2)", "Workloads (工作負載介紹)" (a term and its gloss) and URLs stay
    And   each change is listed in the checks file under what was changed

  @S-writing-gate-010
  Scenario: one strong tell or two weak ones start an edit; one weak tell does not
    Given texts with only emoji bullets, with emoji bullets and four equal paragraphs, and with "說到底，"
    When  the gate runs
    Then  the first is left as written, the second and third are edited

  @S-writing-gate-011
  Scenario: a contrast is a tell only when its second half is empty
    Given "這不是技巧，而是心態。" and "這不是加機器，而是把查詢從 3 秒降到 0.2 秒。"
    When  the rule check runs
    Then  the first is a strong tell "hollow_contrast" and the second is not flagged
    And   the reversed form counts too: "要管的是 AI「默默改變做法」，不是創新本身。" and "It's a habit, not a tool." are strong
          tells, "瓶頸是 3 秒的查詢，不是機器。" is not

  @S-writing-gate-012
  Scenario: quoted words and the article title are not tells
    Given a post quoting 「值得一提的是」 and an article titled "說到底，K8s 是什麼"
    When  the rule check runs with that title protected
    Then  neither is flagged

  @S-writing-gate-013
  Scenario: an edit may not add or drop facts
    Given a text with "40%" and the article URL, sources that mention 40% and 2025
    When  the edit returns a text with "60%" and no URL
    Then  "unsupported_detail 60%" and "lost_link" are must-fix, the edit prompt asked to keep every claim and add none,
          and the next edit receives those reasons

  @S-writing-gate-014
  Scenario: Chinese and English staging tells are caught
    Given texts with "真正的問題是", "讓我們來看看", "我不是說", "希望這對你有幫助" and their English counterparts
    When  the rule check runs
    Then  they are strong tells "deep_saying", "run_up", "straw_man" and "chatbot_residue"
    And   an objection nobody raised is a "straw_man" too: "有人會說這樣綁手綁腳", "你可能會覺得", "Some might say"

  @S-writing-gate-015
  Scenario: block characters and dashes are removed from every text the tool writes
    Given "重點 ▋ 先看結果——再談方法。2020–2025 年，「原文——引述」不動。"
    When  the fix-up runs
    Then  it becomes "重點 先看結果，再談方法。2020-2025 年，「原文——引述」不動。": ▋ and the other block characters (U+2580-U+259F, ■, ▮) are deleted,
          a dash between digits becomes "-", other dashes become a comma, and quoted text keeps its dashes
    And   a block character left in a text is a must-fix "block_char"

  @S-writing-gate-016
  Scenario: casual punctuation turns full-width marks into half-width ones and keeps the full stop
    Given the punctuation style "casual" and "先看結果，再談方法；重點是「迴圈」（不是能力）。真的嗎？是的！\n下一段：結束。"
    When  the fix-up runs
    Then  it becomes "先看結果, 再談方法, 重點是 \"迴圈\" (不是能力)。真的嗎? 是的!\n下一段: 結束。": ，、； become ", ", ：！？ become ": " "! " "? ",
          「」『』“” become \", （） become (), 。 stays (a space would not mark the sentence end next to Latin text or a figure); spaces are not doubled
    And   a half-width , ; : ! ? already in the text gets one space after it ("鎖定帳號,例如 root" becomes "鎖定帳號, 例如 root"), except inside a number ("1,000", "10:30"), in a URL, or before a space, a line end or a closing mark
    And   with "casual" a full-width mark other than 。 left in a text is a must-fix "fullwidth_punctuation" and half-width marks are not a tell;
          the style "full" (the default) keeps S-writing-gate-008 and 009 as they are
```

## Must NOT
- @N-writing-gate-001 a reply or post that failed the gate is written without a warning header; a revision paragraph that failed is not listed as failed in its plan's checks file

## Revisions
- 2026-11-02 · created · decision: none -- no feature checks generated prose for machine-like writing: decision covers which outputs are written, review-panel checks the article, not our own text
- 2026-11-02 · +S-writing-gate-001..007 +N-writing-gate-001 · decision: none -- user: replies and share posts must lose the "AI taste" behind a checklist gate; platform limits checked on 2026-11-02 (sources in data/platforms.json)
- 2026-11-02 · +S-writing-gate-008 · decision: none -- live share run: zh-TW posts came back with ASCII commas and colons between Chinese characters
- 2026-11-02 · ~S-writing-gate-001..002 ~S-writing-gate-005..008 +S-writing-gate-009..014 · decision: none -- user: de-AI must edit the text, not only check it; borrowed from humanizer (edit workflow, strong vs weak-alone tells, when not to act, keep facts), content-skills (hollow vs earned contrast), stop-slop (pattern families); Chinese tells written here
- 2026-11-02 · ~N-writing-gate-001 · decision: none -- revision plans pass the gate too; a header inside the adopted article would end up in audit.md, so their failures go to the plan's checks file
- 2026-11-02 · ~S-writing-gate-009 · decision: none -- live audit: "Term (中文註解)" list items were turned into "Term （…）"; only a parenthesis glued to a Han character is converted
- 2026-11-03 · ~S-writing-gate-002 ~S-writing-gate-010 +S-writing-gate-015..016 · decision: none -- user: de-AI also means no ▋, no —— and, in social posts, no full-width punctuation (half-width, or none); replies and revised articles keep full-width, the Taiwan norm
- 2026-11-06 · ~S-writing-gate-016 casual keeps 。: as a space it could not be told from the gap before Latin text or a figure ("可以用超過 256 位元組的密碼登入 OpenSSH 10.6p2 已經推出") (user: 其中有多處兩句子間沒有「符號」…; 保留「。」) · decision: none -- a refinement of the casual style the user asked for on 2026-11-03
- 2026-11-06 · ~S-writing-gate-016 a half-width mark the model wrote gets the space after it too (user: 同時若中文只是","等類似的符合時，後面加個空白) · decision: none -- the casual style's own spacing rule, applied to marks that were already half width
- 2026-11-06 · ~S-writing-gate-011 ~S-writing-gate-014 · decision: none -- live share run (vault particles): "要管的是 AI「默默改變做法」，不是創新本身" and "有人會說這樣綁手綁腳" passed the rule check; user: add them

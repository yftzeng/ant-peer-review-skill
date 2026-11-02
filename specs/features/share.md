# Feature: share

A third purpose next to audit and drafting: the user read someone else's
article and wants posts that share it with their own followers, in their own
voice, on the platforms they pick (Facebook, Threads, Instagram, X/Twitter,
LinkedIn, LINE, in that order). The article is still reviewed and
fact-checked, so the user does not pass on errors; there is no revision.
Each platform has its own voice file, learned from the user's past posts
there; the share styles (summary, insight, question, addon, pick) are
preselected from that voice. Every post passes the writing gate.

```gherkin
Feature: share
  @S-share-001
  Scenario: the share intake asks for platforms, voices, stance, the user's own take and styles, not the audience card
    Given a voice file for LinkedIn whose posts were mostly "insight", and no other voice file
    When  the user chooses purpose "share", enters a URL, ticks X as well and borrows the LinkedIn voice for X
    Then  after the content check a checkbox lists Facebook, Threads, Instagram, X/Twitter, LinkedIn, LINE in that order
          with LinkedIn ticked; X, having no voice, is asked whether to create one, borrow LinkedIn's, write neutrally,
          or write neutrally and never ask again; LinkedIn is not asked and its voice is shown as applied;
          then the stance (recommend, extend, reserved, rebut), an optional own take,
          and one style checkbox per platform with LinkedIn preselecting "insight" and X preselecting "summary"
    And   no audience card and no brand are asked, and 00-intake.json holds share {platforms, angle "comment", stance, take, styles, voices}
          with voices {x: "borrow", linkedin: "own"}

  @S-share-002
  Scenario: a voice file is learned from pasted posts, per platform
    When  "ant-peer-review voice linkedin" runs and the user pastes three posts separated by "---", then allows "扎實" and denies "賦能"
    Then  one model call describes the voice and counts the posts per style,
          voices/linkedin.json holds that description, the style counts, the median length, the allow and deny words
    And   "ant-peer-review voice list" shows LinkedIn with its post count and the other platforms as missing

  @S-share-003
  Scenario: a platform without a voice borrows the nearest one
    Given a voice file for Threads only
    When  posts are written for X
    Then  X uses the Threads voice adjusted to X's register, and share-checks.md says the voice was borrowed from Threads

  @S-share-004
  Scenario: a share run reviews the article, skips the revision, and writes one post per platform and style
    Given a share run for X (summary) and Instagram (summary, insight) with stance "recommend"
    When  the run reaches the decision
    Then  no revision plans are written, the decision asks for no plan,
          one call writes share-x-summary.md, share-instagram-summary.md and share-instagram-insight.md as plain text,
          the X post carries the article URL without tracking parameters (utm_*, sc=…) and Instagram names the article and author without a link,
          each passed the writing gate with the platform's limits, share-checks.md lists the checks,
          and review.md says whether the article is fit to share

  @S-share-005
  Scenario: a vetoed article is not recommended for sharing
    Given a share run whose "hallucination" red line is confirmed
    When  the posts are written
    Then  each post file starts with a warning that sharing is not recommended and names the red line
    And   review.md says the article is not fit to share

  @S-share-006
  Scenario: share runs non-interactively from arguments
    When  "ant-peer-review new --yes --purpose share --target <text> --platform x,linkedin --stance recommend --take '我們也遇過'" runs, then "decide <run> --yes"
    Then  the run pauses at the decision, and decide writes share-x-summary.md and share-linkedin-insight.md (the platform defaults)
    And   an unknown platform or stance is refused with the allowed values

  @S-share-007
  Scenario: a missing voice is created inside the intake and preselects the style at once
    Given no voice file
    When  the user ticks Threads, chooses "create it now", pastes three posts separated by "---", allows one word and denies one
    Then  one model call builds voices/threads.json, the Threads style checkbox preselects that voice's most used style,
          and the run records voices {threads: "own"}
    And   on a later run the style checkbox for Threads offers "rebuild this platform's voice"; ticking it asks for posts again,
          replaces the voice file and asks the styles again

  @S-share-008
  Scenario: a neutral voice is honoured, and "never ask" is remembered
    Given a voice file for Threads only
    When  the user ticks X and chooses "neutral, and never ask again for this platform"
    Then  the X post is written with no voice even though Threads' could be borrowed,
          and the next share intake does not ask about X's voice

  @S-share-009
  Scenario: a share run neither weighs nor scores the article; fitness rests on red lines and facts
    Given an interactive share run, and a share run whose article has no confirmed red line and one unsupported claim
    When  the run goes from the sources to the decision
    Then  no structure-weight step is asked (and --weights is ignored),
          the report and review.md show no total, grade or per-dimension scores, and the writer is not given them
    And   review.md says the article can be shared while leaving out the unsupported claim, which it names;
          with no unsupported claim it says fit to share, and with a confirmed red line not fit to share, whatever the scores

  @S-share-010
  Scenario: the share intake asks for an angle first; distilling asks no stance and offers two styles
    When  the user chooses purpose "share", enters a text, keeps the output language and picks the angle "distill"
    Then  the angle question lists "comment" (論評此文) and "distill" (概念提純), before the platforms
    And   no stance is asked, each platform's style checkbox offers only "insight" and "question" (insight preselected),
          a question asks whether to end with a source line (yes by default),
          and 00-intake.json holds share {angle: "distill", credit: true} with no stance

  @S-share-011
  Scenario: a distilled post names no one from the article and ends with the source line
    Given a distill share run for X and Instagram whose article is by "Jane Roe" at "Example News" and mentions "Acme"
    When  the analysis lists the names ["Acme"] and the writer returns an X post that says "Acme" and an Instagram post that names no one
    Then  the X post fails with must-fix "name_leak Acme" and is rewritten; author and site count as names too
    And   neither post needs a concrete detail of the article or its title in the body,
          the X file ends with "延伸自：Title https://ex.example/a" and the Instagram file with "延伸自：Title" and no link,
          the platform limit counts the source line; with credit off no source line is added

  @S-share-012
  Scenario: the judge checks a distilled post against the analysis, not in isolation
    When  a distill post is judged
    Then  the judge is given the analysis (purpose, claims and their actions, direction, thesis, anchors) and also answers, each strong
          and failing only with quoted words of the post: "platitude" (the point is one nobody would dispute),
          "paraphrase" (it restates the article's or the subject's own pitch), "ignores_review" (it leans on a claim the analysis drops
          or leaves out its main correction) and "direction" (it does not take the analysis's direction)

  @S-share-013
  Scenario: the angle and the source line from arguments
    When  "ant-peer-review new --yes --purpose share --target <text> --platform x --angle distill --no-credit" runs
    Then  00-intake.json holds share {angle: "distill", credit: false, styles {x: ["insight"]}} and no stance
    And   without --angle the angle is "comment"; "--angle rant" is refused with the allowed values

  @S-share-014
  Scenario: distilling starts with an analysis of the article's purpose and of each claim's truth
    Given a distill run whose fact-check marks "幾分鐘內搞定" unsupported and "純 Rust" supported, with a confirmed hallucination
    When  the posts are written
    Then  one "share_analysis" call before the posts gets the article, the review findings, the red lines and every checked claim
          with its status and reason, and a suggested direction ("oppose or middle" here: a red line is confirmed)
    And   it returns the article's purpose, each claim with an action (keep, strengthen, qualify, drop, correct, avoid),
          a direction (reinforce, oppose or middle) with its reason, a thesis someone could dispute, at least one anchor and the names;
          an unsupported claim marked keep becomes drop, and the analysis is written to share-analysis.md
    And   each analysis row names the checked claims it covers by id, and its status is the fact-check's status, never the model's
          own words; an unsupported claim no row covers is added once, near-duplicates ("佔用"/"占用", "搞定"/"完成") as one row
    And   the posts call gets the analysis instead of the article text, and a post carrying a number from a dropped claim
          fails with must-fix "dropped_claim"

  @S-share-015
  Scenario: in a share run the first target is the article and the rest are references
    Given a share run with the article text as target 1 and the project's GitHub page as target 2
    When  the analysis is written
    Then  the article excerpt holds only document D1, and D2 is given apart as a reference that may be the subject's own description,
          not neutral evidence

  @S-share-016
  Scenario: a distilled post that corrects the article is not marked "not recommended"
    Given a distill run with a confirmed red line whose analysis direction is "oppose" or "middle"
    When  the posts pass the gate
    Then  each post starts with "原文有紅線（…），本文以更正為方向" instead of "不建議分享"; a comment-angle post keeps "不建議分享"
```

## Must NOT
- @N-share-001 a share post speaks of the user's own experience beyond what the user wrote as their take

## Revisions
- 2026-11-02 · created · decision: none -- audit writes to the author and drafting writes a new piece for readers; nothing writes a post that recommends someone else's article to the user's own followers, in the user's own voice per platform
- 2026-11-02 · +S-share-001..006 +N-share-001 · decision: none -- user: share mode; platforms multi-select in the order X/Twitter, Facebook, Threads, Instagram, LinkedIn, LINE; the voice follows the platform and preselects the style instead of being picked separately
- 2026-11-02 · ~S-share-004 · decision: none -- live share run: the shared link kept ithelp's ?sc=rss.iron tracking parameter
- 2026-11-02 · ~S-share-001 +S-share-007..008 · decision: none -- user: the voice should come up during the interaction, not only through a separate command; it is asked only for platforms without one, then applied automatically
- 2026-11-02 · ~S-share-001 · decision: none -- user: platform order Facebook, Threads, Instagram, X/Twitter, LinkedIn, LINE
- 2026-11-02 · +S-share-009 · decision: none -- user: share mode should skip the structure weights and not score the article; whether to share it rests on red lines and the fact-check, not on writing quality
- 2026-11-02 · ~S-share-001 +S-share-010..013 · decision: none -- user: a share angle, one of comment (reuse, extend or critique the article: the existing stances) or distill (filter out people and company names, distill the underlying logic, and develop it with independent thinking); the source line keeps distilling from becoming plagiarism
- 2026-11-02 · ~S-share-011..012 +S-share-014..016 · decision: none -- live distill run (craft-anything): the posts ignored the confirmed hallucination and PR landmine, distilled the project's README (passed as a second target and merged into the article) into a truism, and the judge, seeing only the post, passed it; user: dig out the article's purpose, keep or strengthen what is true, drop or correct what is false, and land on reinforce, oppose or a middle view, never empty or self-evident
- 2026-11-03 · ~S-share-014 · decision: none -- live distill run: the claims table listed near-duplicate ledger claims twice (佔/占, 搞定/完成) and showed the model's own status words when it reworded a claim

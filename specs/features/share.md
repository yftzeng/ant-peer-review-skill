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
    And   no audience card and no brand are asked, and 00-intake.json holds share {platforms, stance, take, styles, voices}
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

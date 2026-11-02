# Feature: share

A third purpose next to audit and drafting: the user read someone else's
article and wants posts that share it with their own followers, in their own
voice, on the platforms they pick (X/Twitter, Facebook, Threads, Instagram,
LinkedIn, LINE, in that order). The article is still reviewed and
fact-checked, so the user does not pass on errors; there is no revision.
Each platform has its own voice file, learned from the user's past posts
there; the share styles (summary, insight, question, addon, pick) are
preselected from that voice. Every post passes the writing gate.

```gherkin
Feature: share
  @S-share-001
  Scenario: the share intake asks for platforms, stance, the user's own take and styles, not the audience card
    Given a voice file for LinkedIn whose posts were mostly "insight", and no other voice file
    When  the user chooses purpose "share", enters a URL and goes through the intake
    Then  after the content check a checkbox lists X/Twitter, Facebook, Threads, Instagram, LinkedIn, LINE in that order
          with LinkedIn ticked, then the stance (recommend, extend, reserved, rebut), then an optional own take,
          then one style checkbox per chosen platform with LinkedIn preselecting "insight" and X preselecting "summary"
    And   no audience card and no brand are asked, and 00-intake.json holds share {platforms, stance, take, styles}

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
```

## Must NOT
- @N-share-001 a share post speaks of the user's own experience beyond what the user wrote as their take

## Revisions
- 2026-11-02 · created · decision: none -- audit writes to the author and drafting writes a new piece for readers; nothing writes a post that recommends someone else's article to the user's own followers, in the user's own voice per platform
- 2026-11-02 · +S-share-001..006 +N-share-001 · decision: none -- user: share mode; platforms multi-select in the order X/Twitter, Facebook, Threads, Instagram, LinkedIn, LINE; the voice follows the platform and preselects the style instead of being picked separately
- 2026-11-02 · ~S-share-004 · decision: none -- live share run: the shared link kept ithelp's ?sc=rss.iron tracking parameter

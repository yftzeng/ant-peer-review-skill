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
          with Facebook (the default platform) and LinkedIn (it has a voice) ticked, and the user unticks Facebook; X, having no voice, is asked whether to create one, borrow LinkedIn's, write neutrally,
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
          a question asks whether to end with a source line (yes by default, neither answer marked as recommended),
          and 00-intake.json holds share {angle: "distill", credit: true} with no stance
    And   with no voice file at all, Facebook alone is ticked in the platform checkbox

  @S-share-011
  Scenario: a distilled post leaves out the original creators and ends with the source line
    Given a distill share run for X and Instagram whose article is by "Jane Roe" at "Example News" and reports work by "Acme"
    When  the analysis lists the origin ["Acme"] and the subject terms ["Rust"], and the writer returns an X post that says "Acme"
          and an Instagram post that names no one from the origin
    Then  the X post fails with must-fix "name_leak Acme" and is rewritten; the article's author and site count as origin too
    And   the subject, its main players and related people (products, models, benchmarks, techniques) are named freely
    And   neither post needs a concrete detail of the article or its title in the body,
          the X file ends with "延伸自：Title https://ex.example/a" and the Instagram file with "延伸自：Title" and no link,
          the platform limit counts the source line; with credit off no source line is added

  @S-share-012
  Scenario: the judge checks a distilled post against the analysis, not in isolation
    When  a distill post is judged
    Then  the judge is given the analysis (purpose, claims and their actions, direction, thesis, anchors) and also answers, each strong
          and failing only with quoted words of the post: "platitude" (the point is one nobody would dispute),
          "paraphrase" (it restates the article's or the subject's own pitch), "ignores_review" (it leans on a claim the analysis drops
          or leaves out its main correction), "direction" (it does not take the analysis's direction) and "no_subject"
          (a reader of the post alone cannot tell what field and what thing it is about)
    And   "unsupported_detail", strong: it fails when the post tells how something happened (how an error was found, how easy
          it was to see, the order of events) in a way the analysis does not state

  @S-share-013
  Scenario: the angle and the source line from arguments
    When  "ant-peer-review new --yes --purpose share --target <text> --platform x --angle distill" runs
    Then  00-intake.json holds share {angle: "distill", credit: true, styles {x: ["insight"]}} and no stance;
          with "--no-credit" credit is false, and "--credit" is still accepted and keeps it true
    And   without --angle the angle is "comment"; "--angle rant" is refused with the allowed values
    And   without --platform the platforms are ["facebook"]

  @S-share-014
  Scenario: distilling starts with an analysis of the article's purpose and of each claim's truth
    Given a distill run whose fact-check marks "幾分鐘內搞定" unsupported and "純 Rust" supported, with a confirmed hallucination
    When  the posts are written
    Then  one "share_analysis" call before the posts gets the article, the review findings, the red lines and every checked claim
          with its status and reason, and a suggested direction ("oppose or middle" here: a red line is confirmed)
    And   it returns the article's purpose, the subject (a one-line topic and 2-4 terms a reader needs), each claim with an action
          (keep, strengthen, qualify, drop, correct, avoid), a direction (reinforce, oppose or middle) with its reason,
          a thesis someone could dispute, at least one anchor (which may name the subject; it states only what the article
          says, and an inference is marked as one) and the origin
          (the article's author and the creators of the work it reports, their organizations, sites and publications);
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

  @S-share-017
  Scenario: a distilled post that leaves out its subject fails
    Given a distill run whose analysis has the topic "editing neural network weights with an LLM" and the terms
          ["GPT-6 Astra", "MATH-500", "權重"]
    When  the writer returns a post that says "一個小模型的數學基準" and names none of them
    Then  it fails with must-fix "missing_subject GPT-6 Astra" and "missing_subject MATH-500" and is rewritten;
          a term without Latin letters or digits ("權重") is left to the judge, since another output language words it differently
    And   a term is looked for as the output language's fix-up writes it: "冷凍電鏡（cryo-EM）" is met by "冷凍電子顯微鏡（cryo-EM）" in zh-TW
    And   a term with a parenthesis is met when each of its parts appears, in either order: "vault（穹窿體）" is met by
          "穹窿體（vault）", and missing either part still fails
    And   the writing rules say: no original creators, companies or sites; open with the topic and the main subject

  @S-share-018
  Scenario: share posts use the punctuation of the user's own posts; without one, full-width in zh-TW
    Given a Threads voice learned from posts written with half-width marks, and no Facebook voice
    When  posts for Facebook and Threads are written in zh-TW
    Then  the Facebook post is checked and fixed with the punctuation style "full" and Threads with "casual",
          and each post's writing brief states its punctuation
    And   without a voice of the user's own, a post in zh-CN or en is "casual"
    And   a voice file learned from posts with half-width marks or none has the style "casual"; a voice file from before this
          change gets its style from its stored samples
  @S-share-019
  Scenario: the reader mix is proposed from the topic's stage and confirmed before the posts are written
    Given a share run whose SC1 says "tipping_point" with status "unsupported"
    When  decide runs interactively
    Then  one model call proposes weights for public, beginner, expert and business that sum to 100, a reason for each,
          and the basis (adoption stage and whether it was checked, technical maturity, media spread)
    And   the user confirms them or types "public=25,beginner=30,expert=30,business=15"; share-readers.json holds the weights,
          the reasons and who set them
    And   with --yes, or deliver alone, the proposal is used unless --readers is given; weights that do not sum to 100 or
          name an unknown reader are a usage error; a failed call gives 25 each and says so; a mix given with --readers
          shows "set by you" in readers.md instead of empty reasons

  @S-share-020
  Scenario: each reader reports whether its goal was met, not how to edit
    Given posts that passed the writing gate and the weights public 25, beginner 30, expert 30, business 15
    When  the readers read them
    Then  four calls run in parallel, each seeing only the posts, its own persona, goal and weight
    And   each returns per post a verdict met, partly or not_met with its hook, peak, stuck point, takeaway, the goal actions it
          would and would not take, and the reason, quoting the post; its schema has no field for edits, facts or tone

  @S-share-021
  Scenario: the writer rules on the reader reports, and the revision passes the gate before readers see it
    Given round-1 reports where the expert says met and the others partly
    When  the writer revises
    Then  one call rules on every reader point (accept, reject, partly, with a reason) and rewrites the posts, the rewritten
          posts pass the writing gate, and the readers read them again
    And   the readers read each post with the source line it will carry; the writer's rules say length is no defect:
          cut only filler and repetition, never background a reader needs; a point a reader finds late moves up, and when a
          reader finds too many terms, the terms the point does not need are dropped before any is explained
    And   after the second round the last revision passes the gate and is final; when every reader says met the loop stops
    And   share-readers.md lists the weights and reasons, each round's verdict per reader and post, and the rulings

  @S-share-022
  Scenario: a first-person experience the take does not state fails, even when there is a take
    Given the take "focus on the sentence about normal things"
    When  a post says "我現在給 AI 代理的指示會多加這段"
    Then  the judge check invented_experience fails it as must-fix, quoting those words, and the rewrite removes it

  @S-share-023
  Scenario: the share analysis leaves out the S-curve check and is never empty
    Given a ledger with SC1 "…Suggested evidence search: … 2026" marked unsupported
    When  the share analysis is written
    Then  SC1 is not a claim row and 2026 is not a number the post must avoid
    And   an analysis with no purpose and no thesis is asked once more, and still empty it raises a backend error
    And   when that reply was refused the error says so and why: claude-cli marks a reply with safety stops as refused,
          "stopped by the safety classifier", and keeps none of its output, even when a fallback model finished it

  @S-share-024
  Scenario: a distilled post names its subject in the output language
    When  a distilled post is written in zh-TW about "vault particles", which the checked claims call "穹窿體"
    Then  the writing rules say to name the subject with the term the checked claims use in the output language, the original
          term once in parentheses, and to put the takeaway and the hook in the opening lines (before the fold), then the
          evidence in order of importance, background last and only what a reader needs (S-share-026)
  @S-share-026
  Scenario: a post on a platform with a fold opens with a headline and follows the inverted pyramid
    Given a share run for Facebook (fold 125) and X (no fold)
    When  the posts are written
    Then  the writing rules say: inverted pyramid, the headline states the single most important fact or point precisely and
          briefly as a statement, then a lede with who, what and why it matters, then details by importance, background last;
          no clickbait
    And   a Facebook post longer than its fold whose first line runs past 40 units (one CJK character or one word each) is a
          must-fix "no_headline" and is rewritten; a post that fits before the fold, and an X post, are not checked for one

  @S-share-027
  Scenario: delivering again reuses the share analysis made from the same inputs
    Given a distill run whose share analysis was written
    When  it is delivered again
    Then  no analysis call is made and the posts are written from share-analysis.json
    And   "--fresh-analysis" makes one; so does a changed input (the person's own take, the article, the checked claims);
          an analysis written before its inputs were recorded is reused as it is

  @S-share-025
  Scenario: a writer that returns no post is asked once more, then fails out loud
    Given a share run whose writing call returns no post for any key, or a refusal
    When  the posts are written
    Then  the call is made once more; still nothing, it raises a backend error naming the refusal if there was one,
          deliver prints the failure instead of "分享文：—", and no reader is asked
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
- 2026-11-03 · ~S-share-001 ~S-share-010 ~S-share-013 · decision: none -- user: tick Facebook by default; no source line by default (the analysis, own thesis and the paraphrase check now keep a distilled post from copying the article)
- 2026-11-03 · ~S-share-011 ~S-share-012 ~S-share-014 +S-share-017 · decision: none -- live distill run (weight-space programming): the post named none of GPT-6 Astra, Qwen3.5-0.8B, MATH-500, because every product, benchmark and even Python was banned as a name; user: leave out the original creators, companies and sites; focus on the topic, the main subject and related people
- 2026-11-03 · +S-share-018 · decision: none -- user: social posts without full-width punctuation; the voice already learns from the user's own posts, so it learns their punctuation too
- 2026-11-06 · S-share-018 unchanged in steps: casual posts now keep 。 at a sentence end (S-writing-gate-016) · decision: none -- see writing-gate
- 2026-11-06 · +S-share-019..024 · decision: none -- live distill run (vault particles): the analysis came back empty, so the post jumped to the take with no background and an English term; user: weigh four readers (public, beginner, expert, business) from the topic's stage, maturity and media spread, confirm the mix, then let each reader report only whether its goal was met, rule on the reports, de-AI before each review and at the end, at most two rounds
- 2026-11-06 · ~S-share-018 · decision: none -- user: zh-TW Facebook posts read oddly with half-width marks; without a voice of the user's own, zh-TW posts use full-width punctuation (reverses the 2026-11-03 default for zh-TW only)
- 2026-11-06 · ~S-share-010 ~S-share-013 ~S-share-019 ~S-share-021 · decision: none -- live rerun (vault particles): readers outside the field could not tell what the post was about; user: give them the original article as a reference point, so a distilled post ends with the source line by default (reverses 2026-11-03); no length limit, only no AI tone or filler
- 2026-11-06 · ~S-share-021 ~S-share-024 · decision: none -- live rerun (vault particles): "background before the take" pushed the point to the last two paragraphs (beginner: only the end was usable) and the writer answered "too many terms" by explaining each one; user agreed: point first, then needed background, then evidence
- 2026-11-06 · +S-share-025 · decision: none -- live rerun (vault particles): the writing call came back with no post and deliver printed "分享文：—" as if it had worked, leaving the old file in place
- 2026-11-06 · ~S-share-017 · decision: none -- live rerun (vault particles): the fix-up wrote 電鏡 as 電子顯微鏡 (S-output-language-003), then the subject check looked for the analysis's "冷凍電鏡（cryo-EM）" and failed the post
- 2026-11-06 · ~S-share-024 +S-share-026 · decision: none -- user: share posts had no proper headline; posts follow the inverted pyramid, the headline and lede state the core fact precisely and briefly, no clickbait
- 2026-11-06 · ~S-share-024 · decision: none -- the order "evidence by importance, background last" was in the spec but not yet in the writing rules (1867037)
- 2026-11-06 · ~S-share-023 · decision: none -- live reruns (vault particles) failed twice with "the share analysis came back empty": the CLI's safety classifier had stopped the call and a fallback model finished it; the run was refused but the message hid it. The fallback output is still not kept (user: 按你建議)
- 2026-11-06 · +S-share-027 · decision: none -- live reruns (vault particles): the analysis call was stopped by the safety classifier in five of six tries, about 1 to 1.8 USD a deliver, while the writing call never was; user: 按你建議 (reuse the analysis, --fresh-analysis to redo it)
- 2026-11-06 · ~S-share-017 · decision: none -- live rerun (vault particles): the analysis listed "vault（穹窿體）" and "cryo-EM（冷凍電子顯微鏡）", the post wrote "穹窿體（vault）" as S-share-024 asks, and failed missing_subject
- 2026-11-06 · ~S-share-012 · decision: none -- two vault-particles reruns wrote "圖一攤開就看得出不對" and "結構圖可以直接檢查，所以很快就被發現", which the article does not say; judged in the same judge call (user: 按你建議)
- 2026-11-06 · ~S-share-014 · decision: none -- the vault-particles analysis wrote the anchor "圖譜能直接檢查，所以很快被發現", which the article does not say, and two posts repeated it; user: 按你建議

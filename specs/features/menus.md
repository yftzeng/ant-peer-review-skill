# Feature: menus

On a real terminal every radio and checkbox is driven with the arrow keys:
↑/↓ move, Enter chooses (radio) or confirms (checkbox), Space toggles, number
keys still work, `c` adds a custom value where custom values are allowed, Esc
cancels like Ctrl-C. The menu redraws in place and collapses to one summary
line when answered. Anywhere else (piped input, `--yes`, Claude driving it,
TERM=dumb, ANT_PEER_REVIEW_PLAIN=1) the numbered prompts stay as they are.

```gherkin
Feature: menus
  @S-menus-001
  Scenario: arrow down then Enter chooses the second radio option
    Given a radio with options "audit" and "drafting" and default "audit"
    When  the keys Down, Enter are pressed
    Then  the answer is "drafting"

  @S-menus-002
  Scenario: Space and number keys toggle a checkbox, Enter confirms
    Given a checkbox with options opus, sonnet, fable and opus ticked
    When  the keys Down, Space, "3", Enter are pressed
    Then  the answer is ["opus", "sonnet", "fable"]

  @S-menus-003
  Scenario: c adds a custom value and ticks it
    Given an audience checkbox that allows custom values
    When  "c" is pressed, "regulators" is typed and Enter is pressed twice
    Then  the answer is ["custom:regulators"]

  @S-menus-004
  Scenario: confirming with too few ticks shows the reason and stays in the menu
    Given a checkbox that needs at least 2 ticks with only opus ticked
    When  Enter is pressed, then Down, Space, Enter
    Then  the reason is shown once and the answer is ["opus", "sonnet"]

  @S-menus-005
  Scenario: the menu collapses to one summary line when answered
    Given a radio titled "Purpose:"
    When  an option is chosen
    Then  the drawn menu is erased and "? Purpose: Audit" is printed in its place

  @S-menus-006
  Scenario: Esc cancels like Ctrl-C
    When  Esc is pressed in a menu
    Then  KeyboardInterrupt is raised

  @S-menus-007
  Scenario: wide labels are cut to the terminal width by display width
    Given a terminal 20 columns wide and a label of 30 CJK characters
    When  the menu is drawn
    Then  every drawn line is at most 20 columns wide

  @S-menus-008
  Scenario: a real pseudo-terminal drives the CLI with arrow keys
    Given the CLI running in a pty with a saved config
    When  Down, Enter is sent at the purpose question
    Then  the run's intake purpose is "drafting"

  @S-menus-009
  Scenario: a long checkbox shows 10 rows a page and keeps ticks across pages
    Given a checkbox of 23 options with page size 10
    When  Space ticks option 1, Right moves to page 2, Space ticks option 11, Left returns, Enter confirms
    Then  each frame shows at most 10 options and "page 1/3" or "page 2/3", and the answer is options 1 and 11

  @S-menus-010
  Scenario: in line mode n and p change page and numbers stay global
    Given the same checkbox without a menu-capable terminal
    When  the user types "n", then "12", then an empty line
    Then  page 2 lists options 11-20 numbered 11-20, and the answer is option 12
```

## Must NOT
- @N-menus-001 piped or non-terminal input switches the terminal into raw/cbreak mode or expects arrow keys

## Revisions
- 2026-10-22 · +S-menus-001..008 +N-menus-001 · decision: none -- user chose stdlib arrow menus (option B) over adding questionary/prompt_toolkit: keeps zero runtime deps and the in-list custom entry
- 2026-10-25 · +S-menus-009..010 · decision: none -- user: the article list shows 10 a page with previous/next page

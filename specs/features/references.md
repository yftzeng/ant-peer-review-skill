# Feature: references

docs/REFERENCES.md records every outside skill this project learned from. Each
GitHub reference names the exact commit that was read, so a later reader sees
the same files, and the maintainer can ask "has anything we borrowed from
changed upstream since?" with one command instead of opening every repo.

```gherkin
Feature: references
  @S-references-001
  Scenario: every GitHub reference is pinned to the commit read
    Given docs/REFERENCES.md
    When  the test reads every https://github.com/ link in it
    Then  each one is /tree/<40-hex commit>/ or /blob/<40-hex commit>/, never a branch such as main
    And   a link whose text carries @<short hash> has a commit that starts with that hash
    And   the file has a line "Upstream last checked: YYYY-MM-DD"

  @S-references-002
  Scenario: refs-drift reports, per pinned path, whether upstream changed it
    Given a reference pinned to commit P for path a/ and another for path b/, and upstream head H changes only b/
    When  "scripts/refs-drift.sh docs/REFERENCES.md" runs
    Then  a/ is reported "moved, path unchanged" and b/ "CHANGED" with each changed file and a compare link P...H
    And   the last line starts "refs-drift: CHANGED" and the exit code is 1

  @S-references-003
  Scenario: refs-drift passes when nothing moved and fails when a repo cannot be read
    Given every pin equals its upstream head
    When  refs-drift runs
    Then  each path is reported "same", the last line starts "refs-drift: PASS" and the exit code is 0
    And   when a referenced repo cannot be cloned the last line starts "refs-drift: FAIL" and the exit code is 2
```

## Must NOT
- @N-references-001 refs-drift never edits docs/REFERENCES.md: it only reports; moving a pin is a reviewed edit by hand

## Revisions
- 2026-10-23 · created · decision: none -- no feature covers docs/REFERENCES.md: how a reference is pinned to the commit read and how upstream drift is checked
- 2026-10-24 · +S-references-001..003 +N-references-001 · decision: none -- user: 開工 (pin each reference to the commit read and check upstream drift with one command)

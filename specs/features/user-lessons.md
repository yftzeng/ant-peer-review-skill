# Feature: user lessons

Per-user lessons learned (crawl incidents, decisions), kept only on the
installing user's machine. Ids are assigned by the tool and never reused; the
index in LESSONS.md lists every id as 本檔 or 封存, and lessons/_archive.md holds
every lesson's full text verbatim. A lesson in an area that already has one is
the second time: the tool proposes a machine rule instead of more text.

```gherkin
Feature: user lessons
  @S-user-lessons-001
  Scenario: a new lesson gets the next id, an index row and an archive copy
    Given an empty store
    When  the user adds lesson "Site X needs JS" with cause, rule and enforced
    Then  LESSONS.md has an index row "L-0001 | Site X needs JS | ... | 本檔" and the full text
    And   lessons/_archive.md has the same full text

  @S-user-lessons-002
  Scenario: ids are never reused, even after the index row is removed
    Given lessons L-0001 and L-0002 exist and L-0002's row was deleted from LESSONS.md by hand
    When  a new lesson is added
    Then  it gets id L-0003

  @S-user-lessons-003
  Scenario: archiving moves the full text out of LESSONS.md but keeps the index row
    Given lesson L-0001 is 本檔
    When  it is archived
    Then  its index row says 封存, its full text is gone from LESSONS.md and still in the archive

  @S-user-lessons-004
  Scenario: the second crawl lesson for a domain proposes a site profile rule
    Given lesson L-0001 in area "crawl/example.com"
    When  another lesson in area "crawl/example.com" is added and the user accepts blocking it
    Then  site-profiles.json marks "example.com" blocked with a note naming both lessons

  @S-user-lessons-005
  Scenario: reading lessons filters by area
    Given lessons in areas "crawl/a.com", "factcheck" and "crawl/b.com"
    When  lessons are listed for area prefix "crawl/"
    Then  only the two crawl lessons are returned
```

## Must NOT
- @N-user-lessons-001 a lesson is written to the installed package directory

## Revisions
- 2026-10-22 · +S-user-lessons-001..005 +N-user-lessons-001 · decision: none -- follows docs/DESIGN.md §6

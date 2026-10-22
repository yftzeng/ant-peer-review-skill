import pytest

from ant_peer_review.i18n import T
from ant_peer_review.jsonio import read_json
from ant_peer_review.lessons import (add_lesson, archive_lesson, lessons_for,
                                     promote_if_repeated)
from ant_peer_review.store import PACKAGE_DIR
from ant_peer_review.ui import ScriptedIO

KW = dict(cause="c", rule="r", enforced="judgment")


# @S-user-lessons-001
def test_new_lesson_index_and_archive(store):
    lid = add_lesson(store, "Site X needs JS", area="crawl/x.com", **KW)
    assert lid == "L-0001"
    idx = store.lessons_md.read_text()
    assert "| L-0001 | Site X needs JS | crawl/x.com | 本檔 |" in idx
    assert "## L-0001 Site X needs JS" in idx
    assert "## L-0001 Site X needs JS" in (store.lessons_dir / "_archive.md").read_text()


# @S-user-lessons-002
def test_ids_never_reused(store):
    add_lesson(store, "one", area="a", **KW)
    add_lesson(store, "two", area="a", **KW)
    text = store.lessons_md.read_text().replace("| L-0002 | two | a | 本檔 |\n", "")
    store.lessons_md.write_text(text)
    (store.lessons_dir / ".next_id").unlink()
    assert add_lesson(store, "three", area="a", **KW) == "L-0003"


# @S-user-lessons-003
def test_archive_moves_text(store):
    add_lesson(store, "one", area="a", **KW)
    archive_lesson(store, "L-0001")
    idx = store.lessons_md.read_text()
    assert "| L-0001 | one | a | 封存 |" in idx and "## L-0001" not in idx
    assert "## L-0001 one" in (store.lessons_dir / "_archive.md").read_text()


# @S-user-lessons-004
def test_second_crawl_lesson_promotes(store):
    add_lesson(store, "blocked once", area="crawl/example.com", **KW)
    lid = add_lesson(store, "blocked again", area="crawl/example.com", **KW)
    io = ScriptedIO(["1"])
    promote_if_repeated(io, T("en"), store, lid, "crawl/example.com")
    prof = read_json(store.site_profiles)["example.com"]
    assert prof["blocked"] is True and "L-0001" in prof["note"] and "L-0002" in prof["note"]


# @S-user-lessons-005
def test_filter_by_area(store):
    add_lesson(store, "a", area="crawl/a.com", **KW)
    add_lesson(store, "f", area="factcheck", **KW)
    add_lesson(store, "b", area="crawl/b.com", **KW)
    assert [x["title"] for x in lessons_for(store, "crawl/")] == ["a", "b"]


# @N-user-lessons-001
def test_lessons_live_in_store_not_package(store):
    add_lesson(store, "x", area="a", **KW)
    assert PACKAGE_DIR not in store.lessons_md.resolve().parents
    assert not list(PACKAGE_DIR.rglob("LESSONS.md"))

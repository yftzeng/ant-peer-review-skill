"""Per-user lessons: LESSONS.md index (本檔 / 封存) + lessons/_archive.md (all, verbatim).

Ids come from max(counter file, highest id in the archive) + 1, so an id is
never reused even if an index row is deleted by hand.
"""
from __future__ import annotations

import re
from datetime import date

from .jsonio import read_json, write_json, write_text_atomic
from .store import Store

HEADER = ("# Lessons\n\nHow this tool should work, learned from runs and corrections.\n"
          "本檔 = full text below; 封存 = full text only in lessons/_archive.md.\n\n"
          "| ID | Title | Area | Where |\n|---|---|---|---|\n")
ID_RE = re.compile(r"^## (L-\d{4}) ", re.M)


def _archive(store: Store):
    return store.lessons_dir / "_archive.md"


def _counter(store: Store):
    return store.lessons_dir / ".next_id"


def next_id(store: Store) -> str:
    c = _counter(store)
    n_counter = int(c.read_text().strip()) if c.exists() else 1
    arch = _archive(store)
    ids = [int(x[2:]) for x in ID_RE.findall(arch.read_text(encoding="utf-8"))] if arch.exists() else []
    n = max(n_counter, max(ids, default=0) + 1)
    return f"L-{n:04d}"


def _block(lid: str, title: str, area: str, cause: str, rule: str, enforced: str) -> str:
    return (f"## {lid} {title}\n- Date: {date.today().isoformat()}\n- Area: {area}\n"
            f"- Cause: {cause}\n- Rule: {rule}\n- Enforced: {enforced}\n\n")


def _read_index(store: Store) -> tuple[list[list[str]], str]:
    p = store.lessons_md
    if not p.exists():
        return [], ""
    text = p.read_text(encoding="utf-8")
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")]
            for ln in text.splitlines() if re.match(r"^\| L-\d{4} ", ln)]
    body = text.split("\n## ", 1)
    return rows, ("## " + body[1]) if len(body) > 1 else ""


def _write_index(store: Store, rows: list[list[str]], body: str) -> None:
    table = "".join(f"| {' | '.join(r)} |\n" for r in rows)
    write_text_atomic(store.lessons_md, HEADER + table + "\n" + body)


def all_lessons(store: Store) -> list[dict]:
    arch = _archive(store)
    if not arch.exists():
        return []
    out = []
    for blk in re.split(r"(?=^## L-\d{4} )", arch.read_text(encoding="utf-8"), flags=re.M):
        m = re.match(r"## (L-\d{4}) (.*)\n", blk)
        if not m:
            continue
        fields = dict(re.findall(r"^- (\w+): (.*)$", blk, re.M))
        out.append({"id": m.group(1), "title": m.group(2), "area": fields.get("Area", ""),
                    "cause": fields.get("Cause", ""), "rule": fields.get("Rule", ""),
                    "enforced": fields.get("Enforced", "")})
    return out


def lessons_for(store: Store, area_prefix: str) -> list[dict]:
    return [ls for ls in all_lessons(store) if ls["area"].startswith(area_prefix)]


def add_lesson(store: Store, title: str, *, area: str, cause: str, rule: str, enforced: str,
               archived: bool = False) -> str:
    lid = next_id(store)
    block = _block(lid, title.strip(), area.strip(), cause.strip(), rule.strip(), enforced.strip())
    arch = _archive(store)
    prev = arch.read_text(encoding="utf-8") if arch.exists() else "# Lessons archive (verbatim)\n\n"
    write_text_atomic(arch, prev + block)
    rows, body = _read_index(store)
    rows.append([lid, title.strip().replace("|", "/"), area.strip(), "封存" if archived else "本檔"])
    if not archived:
        body += block
    _write_index(store, rows, body)
    write_text_atomic(_counter(store), str(int(lid[2:]) + 1))
    return lid


def archive_lesson(store: Store, lid: str) -> None:
    rows, body = _read_index(store)
    for r in rows:
        if r[0] == lid:
            r[3] = "封存"
    body = re.sub(rf"^## {lid} .*?(?=^## L-\d{{4}} |\Z)", "", body, flags=re.M | re.S)
    _write_index(store, rows, body)


def same_area_before(store: Store, area: str, exclude: str) -> list[dict]:
    return [ls for ls in all_lessons(store) if ls["area"] == area and ls["id"] != exclude]


def set_site_profile(store: Store, domain: str, **fields) -> dict:
    profiles = read_json(store.site_profiles, default={})
    entry = profiles.get(domain, {})
    entry.update({k: v for k, v in fields.items() if v not in (None, "")})
    profiles[domain] = entry
    write_json(store.site_profiles, profiles)
    return entry


def promote_if_repeated(io, t, store: Store, lid: str, area: str) -> dict | None:
    """Second lesson in the same area: offer a machine rule instead of more text."""
    from .ui import radio
    before = same_area_before(store, area, lid)
    if not before:
        return None
    ids = ", ".join([b["id"] for b in before] + [lid])
    io.say(t("lessons.second_time", area=area, ids=ids))
    if not area.startswith("crawl/"):
        io.say(t("lessons.promote_hint"))
        return None
    domain = area.split("/", 1)[1]
    act = radio(io, t, t("lessons.promote"), [
        ("block", t("lessons.promote.block", domain=domain)),
        ("ua", t("lessons.promote.ua")), ("none", t("lessons.promote.none"))], default="none")
    if act == "block":
        return set_site_profile(store, domain, blocked=True, note=f"lessons {ids}")
    if act == "ua":
        ua = io.ask(t("lessons.ua_prompt") + " ").strip()
        if ua:
            return set_site_profile(store, domain, user_agent=ua, note=f"lessons {ids}")
    return None

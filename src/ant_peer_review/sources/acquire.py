"""P4 sources phase: targets -> raw/ + normalized/ + segments.json + injection-scan.json.

Each target is one work item; a resumed phase retries only items not "ok".
Doc ids are fixed by target position (D<i>, or D<i>-<k> for files of a folder),
so retrying one item never renumbers the others.
"""
from __future__ import annotations

import re
import tempfile
from datetime import datetime
from pathlib import Path

from ..jsonio import read_json, sha256_bytes, write_json, write_text_atomic
from ..workspace import Run
from .converter import ConvertError, convert_file, convert_folder, pdf_to_markdown
from .crawler import Crawler, FetchError
from .feeds import FEED_TYPES
from .quality import page_problem
from .urls import redact
from .htmlmd import html_to_markdown
from .injection import scan
from .segments import segment

THIN_PAGE_CHARS = 200


def _doc_record(run: Run, doc_id: str, origin: str, title: str, markdown: str,
                raw: bytes, raw_name: str, hidden: list[dict]) -> dict:
    raw_path = run.root / "01-sources" / "raw" / raw_name
    if not raw_path.exists():
        run.write_raw_source(raw_name, raw)
    norm = f"01-sources/normalized/{doc_id}.md"
    header = f"<!-- source: {origin} -->\n\n" if origin else ""
    write_text_atomic(run.path(norm), header + markdown + "\n")
    return {"doc": doc_id, "origin": origin, "title": title, "sha256": sha256_bytes(raw),
            "normalized": norm, "hidden": hidden, "chars": len(markdown)}


def _fetch_item(run: Run, crawler: Crawler, idx: int, url: str) -> dict:
    res = crawler.fetch(url)
    doc_id = f"D{idx}"
    hidden: list[dict] = []
    title = ""
    if res.content_type in FEED_TYPES:
        raise FetchError("is_feed", "start a new run with this URL to pick its articles")
    if res.content_type in ("text/html", "application/xhtml+xml"):
        raw = res.body.decode("utf-8", "replace")
        conv = html_to_markdown(raw)
        problem = page_problem(raw, conv.title, conv.markdown)
        if problem:
            raise FetchError(problem, redact(res.final_url))
        md, hidden, title = conv.markdown, conv.hidden, conv.title
        ext = "html"
    elif res.content_type == "application/pdf":
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(res.body)
            f.flush()
            md = pdf_to_markdown(Path(f.name))
        ext = "pdf"
    else:
        md = res.body.decode("utf-8", "replace")
        ext = "txt"
    rec = _doc_record(run, doc_id, redact(res.final_url), title or redact(url), md, res.body,
                      f"{doc_id}.{ext}", hidden)
    item = {"docs": [rec], "final_url": redact(res.final_url), "hops": [redact(h) for h in res.hops]}
    if ext == "html" and len(md) < THIN_PAGE_CHARS:
        item["warning"] = "thin_page_maybe_js_rendered"
    return item


def _path_item(run: Run, idx: int, value: str) -> dict:
    p = Path(value).expanduser()
    if p.is_symlink():
        raise ConvertError("symlink", value)
    if p.is_dir():
        docs, skipped = convert_folder(p)
        recs = []
        for k, d in enumerate(docs, 1):
            doc_id = f"D{idx}-{k}"
            ext = Path(d.origin).suffix.lstrip(".") or "txt"
            recs.append(_doc_record(run, doc_id, d.origin, d.title, d.markdown, d.raw,
                                    f"{doc_id}.{ext}", d.hidden))
        if not recs:
            raise ConvertError("no_supported_files", value)
        return {"docs": recs, "skipped": [{"origin": s.origin, "reason": s.reason}
                                          for s in skipped]}
    if not p.exists():
        raise ConvertError("not_found", value)
    d = convert_file(p)
    doc_id = f"D{idx}"
    ext = p.suffix.lstrip(".") or "txt"
    return {"docs": [_doc_record(run, doc_id, p.name, d.title, d.markdown, d.raw,
                                 f"{doc_id}.{ext}", d.hidden)]}


def _feed_item(run: Run, crawler: Crawler, idx: int, target: dict) -> dict:
    """An article listed by a feed. Its page is the source of truth (feeds can be
    lossy: iThome's strips punctuation); the feed's HTML is only the fallback."""
    try:
        item = _fetch_item(run, crawler, idx, target["value"])
        if item["docs"][0]["chars"]:
            item["docs"][0]["title"] = target.get("title") or item["docs"][0]["title"]
            return item
    except FetchError:
        pass
    conv = html_to_markdown(target.get("html", ""))
    doc_id = f"D{idx}"
    raw_name = f"{doc_id}.feed.html"
    return {"docs": [_doc_record(run, doc_id, redact(target["value"]), target.get("title") or conv.title,
                                 conv.markdown, target.get("html", "").encode("utf-8"),
                                 raw_name, conv.hidden)],
            "warning": "feed_content_maybe_lossy"}


def _text_item(run: Run, idx: int, value: str) -> dict:
    doc_id = f"D{idx}"
    first = value.strip().splitlines()[0].lstrip("#").strip()[:60] if value.strip() else "text"
    return {"docs": [_doc_record(run, doc_id, "", first, value.strip(), value.encode("utf-8"),
                                 f"{doc_id}.txt", [])]}


def run_sources(run: Run, crawler: Crawler, *, on_progress=None) -> dict:
    intake = read_json(run.path("00-intake.json"))
    manifest_path = run.path("01-sources/manifest.json")
    manifest = read_json(manifest_path, default={"items": []})
    prior = {it["item"]: it for it in manifest.get("items", [])}
    items = []
    for idx, target in enumerate(intake["targets"], 1):
        old = prior.get(idx)
        key = sha256_bytes(target["value"].encode("utf-8"))
        if old and old.get("status") == "ok" and old.get("value_sha256") == key:
            items.append(old)
            continue
        shown = redact(target["value"]) if target["kind"] in ("url", "feed_item") else target["value"]
        entry = {"item": idx, "kind": target["kind"], "value": shown, "value_sha256": key,
                 "attempted_at": datetime.now().isoformat(timespec="seconds")}
        try:
            if target["kind"] == "url":
                entry.update(_fetch_item(run, crawler, idx, target["value"]))
            elif target["kind"] == "feed_item":
                entry.update(_feed_item(run, crawler, idx, target))
            elif target["kind"] == "path":
                entry.update(_path_item(run, idx, target["value"]))
            else:
                entry.update(_text_item(run, idx, target["value"]))
            entry["status"] = "ok"
        except (FetchError, ConvertError) as e:
            entry.update(status="failed", reason=e.reason, detail=redact(str(e))[:300])
        items.append(entry)
        if on_progress:
            on_progress(entry)
    manifest = {"items": items}
    write_json(manifest_path, manifest)

    segs: dict[str, list[dict]] = {}
    hidden_all: list[dict] = []
    for it in items:
        for d in it.get("docs", []) if it.get("status") == "ok" else []:
            md = run.path(d["normalized"]).read_text(encoding="utf-8")
            md = re.sub(r"^<!-- source:.*?-->\s*", "", md, flags=re.S)
            doc_num = d["doc"][1:]
            segs[d["doc"]] = segment(md, doc_num)
            hidden_all += [dict(h, doc=d["doc"]) for h in d.get("hidden", [])]
    write_json(run.path("01-sources/segments.json"), segs)
    flat = [s for doc in segs.values() for s in doc]
    write_json(run.path("01-sources/injection-scan.json"), scan(flat, hidden_all))
    return manifest


def failed_items(manifest: dict) -> list[dict]:
    return [it for it in manifest.get("items", []) if it.get("status") != "ok"]

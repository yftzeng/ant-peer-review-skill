"""P4 sources phase: targets -> raw/ + normalized/ + segments.json + injection-scan.json.

Each target is one work item; a resumed phase retries only items not "ok".
Doc ids are fixed by target position (D<i>, or D<i>-<k> for files of a folder),
so retrying one item never renumbers the others.
"""
from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urljoin

from ..jsonio import read_json, sha256_bytes, sha256_file, write_json, write_text_atomic
from ..workspace import Run
from .converter import ConvertError, convert_file, convert_folder, pdf_to_markdown
from .crawler import DEFAULT_UA, Crawler, FetchError
from .feeds import FEED_TYPES
from .quality import page_problem
from .urls import redact
from .htmlmd import html_to_markdown
from .injection import scan
from .render import RenderError
from .segments import segment

THIN_PAGE_CHARS = 200


def _store_raw(run: Run, raw_name: str, raw: bytes) -> str:
    """Raw files are write-once. When the name is taken by other bytes (a retry that got a
    different page), the new bytes go under a name with their hash, so every recorded
    sha256 matches its own file."""
    p = run.root / "01-sources" / "raw" / raw_name
    if p.exists():
        if sha256_file(p) == sha256_bytes(raw):
            return raw_name
        stem, _, ext = raw_name.rpartition(".")
        raw_name = f"{stem}.{sha256_bytes(raw)[:8]}.{ext}"
        if (p.parent / raw_name).exists():
            return raw_name
    run.write_raw_source(raw_name, raw)
    return raw_name


def _doc_record(run: Run, doc_id: str, origin: str, title: str, markdown: str,
                raw: bytes, raw_name: str, hidden: list[dict]) -> dict:
    raw_name = _store_raw(run, raw_name, raw)
    norm = f"01-sources/normalized/{doc_id}.md"
    header = f"<!-- source: {origin} -->\n\n" if origin else ""
    write_text_atomic(run.path(norm), header + markdown + "\n")
    return {"doc": doc_id, "origin": origin, "title": title, "sha256": sha256_bytes(raw),
            "normalized": norm, "hidden": hidden, "chars": len(markdown), "raw": raw_name}


# A site's or our own refusal: honoured, never worked around (D-0001). A paywall
# belongs here too: an archive copy would only route around it.
NO_FALLBACK = {"robots", "site_profile_blocked", "blocked_address", "scheme",
               "credentials_in_url", "bad_url", "no_host", "is_feed", "login_or_paywall"}
# HTTP answers that mean "authenticate", "pay" or "legally unavailable".
NO_FALLBACK_STATUS = {"401", "402", "451"}
# Read like a thin page: the browser, AMP and the archive may help.
THIN_PROBLEMS = {"empty_page"}
# Anything else (a bot challenge, a soft 404, other HTTP errors) may use the archive,
# never the browser: a headless browser that gets past a challenge is the evasion
# D-0001 rules out.
ARCHIVE_API = "https://archive.org/wayback/available?url="
_AMP_RE = re.compile(r"<link\b[^>]*\brel=[\"']?amphtml\b[^>]*>", re.I)
_HREF_RE = re.compile(r"\bhref=[\"']?([^\"'\s>]+)", re.I)


def _convert(res) -> tuple[str, list[dict], str, str, str | None]:
    """(markdown, hidden, title, ext, page problem)."""
    if res.content_type in ("text/html", "application/xhtml+xml"):
        raw = res.body.decode("utf-8", "replace")
        conv = html_to_markdown(raw)
        return (conv.markdown, conv.hidden, conv.title, "html",
                page_problem(raw, conv.title, conv.markdown))
    if res.content_type == "application/pdf":
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(res.body)
            f.flush()
            return pdf_to_markdown(Path(f.name)), [], "", "pdf", None
    return res.body.decode("utf-8", "replace"), [], "", "txt", None


def _profile(crawler, url: str) -> dict:
    fn = getattr(crawler, "profile_for", None)
    return fn(url) if fn else {}


def _ua(crawler, url: str) -> str:
    fn = getattr(crawler, "preflight", None)
    return fn(url) if fn else DEFAULT_UA


def _amp_url(html: bytes, base: str) -> str | None:
    m = _AMP_RE.search(html.decode("utf-8", "replace"))
    href = _HREF_RE.search(m.group(0)) if m else None
    return urljoin(base, href.group(1)) if href else None


def _candidate(md, hidden, title, raw, raw_name, origin, **extra) -> dict:
    """A possible replacement, not written until it is accepted."""
    return {"md": md, "hidden": hidden, "title": title, "raw": raw, "raw_name": raw_name,
            "origin": origin, "extra": extra}


def _rendered(crawler, renderer, idx, url, title):
    def nav_ok(u: str) -> bool:
        if not crawler.request_allowed(u):
            return False
        try:
            _ua(crawler, u)
        except FetchError:
            return False
        return True
    try:
        html, final = renderer.render(url, allow=crawler.request_allowed, allow_navigation=nav_ok,
                                      user_agent=_ua(crawler, url), max_bytes=crawler.max_bytes,
                                      timeout=crawler.timeout * 3)
    except (RenderError, FetchError):
        return None
    if final != url and not nav_ok(final):
        return None  # the page took the browser somewhere robots or the profile refuse
    conv = html_to_markdown(html)
    problem = page_problem(html, conv.title, conv.markdown)
    if problem in NO_FALLBACK:
        raise FetchError(problem, redact(final))
    if problem:
        return None
    return _candidate(conv.markdown, conv.hidden, conv.title or title, html.encode("utf-8"),
                      f"D{idx}.rendered.html", redact(final), via="render")


def _amp(crawler, idx, res, title):
    amp = _amp_url(res.body, res.final_url)
    if not amp:
        return None
    try:
        r = crawler.fetch(amp)
        md, hidden, t2, ext, problem = _convert(r)
    except (FetchError, ConvertError):
        return None
    if problem in NO_FALLBACK:
        raise FetchError(problem, redact(r.final_url))
    if problem:
        return None
    return _candidate(md, hidden, t2 or title, r.body, f"D{idx}.amp.{ext}", redact(r.final_url),
                      via="amp")


def _archive(crawler, idx, url):
    """The newest Wayback Machine snapshot, fetched through the same safe crawler. A URL
    carrying secrets is never sent: it would leak them, and could not be archived anyway."""
    if _profile(crawler, url).get("no_archive") or redact(url) != url:
        return None
    try:
        api = crawler.fetch(ARCHIVE_API + quote(url, safe=""), types=("application/json",))
        snap = json.loads(api.body.decode("utf-8")).get("archived_snapshots", {}).get("closest")
        if not snap or not snap.get("available") or str(snap.get("status", "200")) != "200":
            return None
        ts = str(snap["timestamp"])
        if not re.fullmatch(r"\d{8,14}", ts):
            return None
        r = crawler.fetch(f"https://web.archive.org/web/{ts}id_/{url}")
        md, hidden, title, ext, problem = _convert(r)
    except (FetchError, ConvertError, ValueError, KeyError, AttributeError, TypeError):
        return None
    if problem or not md.strip():
        return None
    human = f"https://web.archive.org/web/{ts}/{url}"
    return _candidate(md, hidden, title or url, r.body, f"D{idx}.archive.{ext}", human,
                      via="archive", archived_at=f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}",
                      archive_url=human)


def _accept(run, idx, cand, live_chars: int) -> dict | None:
    """A candidate replaces the live page only when it has real text, and an archive copy
    only when clearly longer (an older snapshot must not replace a short live page)."""
    if cand is None:
        return None
    floor = 2 * live_chars if cand["extra"]["via"] == "archive" else live_chars
    if len(cand["md"]) < max(THIN_PAGE_CHARS, floor):
        return None
    rec = _doc_record(run, f"D{idx}", cand["origin"], cand["title"], cand["md"], cand["raw"],
                      cand["raw_name"], cand["hidden"])
    return {"docs": [rec], **cand["extra"]}


def _fetch_item(run: Run, crawler: Crawler, idx: int, url: str, renderer=None) -> dict:
    """D-0001 order: crawler (with bounded retries) -> browser for thin, empty or needs_js
    pages -> AMP -> archive. The paste step is offered by the sources phase."""
    profile = _profile(crawler, url)
    try:
        res = crawler.fetch(url)
    except FetchError as e:
        if e.reason in NO_FALLBACK or (e.reason == "http_status" and e.detail in NO_FALLBACK_STATUS):
            raise
        alt = _accept(run, idx, _archive(crawler, idx, url), 0)
        if alt:
            return dict(alt, fell_back_from=e.reason)
        raise
    if res.content_type in FEED_TYPES:
        raise FetchError("is_feed", "start a new run with this URL to pick its articles")
    md, hidden, title, ext, problem = _convert(res)
    if problem in NO_FALLBACK:
        raise FetchError(problem, redact(res.final_url))
    if problem and problem not in THIN_PROBLEMS:
        alt = _accept(run, idx, _archive(crawler, idx, url), 0)
        if alt:
            return dict(alt, fell_back_from=problem)
        raise FetchError(problem, redact(res.final_url))
    base = {"final_url": redact(res.final_url), "hops": [redact(h) for h in res.hops]}
    _store_raw(run, f"D{idx}.{ext}", res.body)  # the original stays, whatever replaces it
    live = len(md.strip())
    thin = ext == "html" and (problem is not None or live < THIN_PAGE_CHARS)
    if ext == "html" and (thin or profile.get("needs_js")):
        steps = []
        if renderer is not None:
            steps.append(lambda: _rendered(crawler, renderer, idx, res.final_url, title))
        if thin:
            steps += [lambda: _amp(crawler, idx, res, title),
                      lambda: _archive(crawler, idx, url)]
        for step in steps:
            alt = _accept(run, idx, step(), live)
            if alt:
                why = problem or ("thin_page" if thin else "needs_js")
                return dict(base, **alt, fell_back_from=why)
    if problem:
        raise FetchError(problem, redact(res.final_url))
    doc_id = f"D{idx}"
    rec = _doc_record(run, doc_id, redact(res.final_url), title or redact(url), md, res.body,
                      f"{doc_id}.{ext}", hidden)
    item = dict(base, docs=[rec], via="direct")
    if thin:
        item["warning"] = "thin_page_maybe_js_rendered" + ("" if renderer else
                                                            "; no_browser_installed")
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


def _feed_item(run: Run, crawler: Crawler, idx: int, target: dict, renderer=None) -> dict:
    """An article listed by a feed. Its page is the source of truth (feeds can be
    lossy: iThome's strips punctuation); the feed's HTML is only the fallback."""
    try:
        item = _fetch_item(run, crawler, idx, target["value"], renderer)
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


def _text_item(run: Run, idx: int, value: str, pasted_for: str = "") -> dict:
    """Free text; pasted_for is the URL the user pasted it from (D-0001, step 4)."""
    doc_id = f"D{idx}"
    first = value.strip().splitlines()[0].lstrip("#").strip()[:60] if value.strip() else "text"
    item = {"docs": [_doc_record(run, doc_id, redact(pasted_for), first, value.strip(),
                                 value.encode("utf-8"), f"{doc_id}.txt", [])]}
    if pasted_for:
        item["via"] = "paste"
    return item


def run_sources(run: Run, crawler: Crawler, *, on_progress=None, renderer=None) -> dict:
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
                entry.update(_fetch_item(run, crawler, idx, target["value"], renderer))
            elif target["kind"] == "feed_item":
                entry.update(_feed_item(run, crawler, idx, target, renderer))
            elif target["kind"] == "path":
                entry.update(_path_item(run, idx, target["value"]))
            else:
                entry.update(_text_item(run, idx, target["value"], target.get("pasted_for", "")))
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

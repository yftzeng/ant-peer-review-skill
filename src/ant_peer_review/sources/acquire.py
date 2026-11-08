"""P4 sources phase: targets -> raw/ + normalized/ + segments.json + injection-scan.json.

Each target is one work item; a resumed phase retries only items not "ok".
Doc ids are fixed by target position (D<i>, or D<i>-<k> for files of a folder),
so retrying one item never renumbers the others.
"""
from __future__ import annotations

import json
import re
import time
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
from .agentready import first_heading, github_raw, html_blocks_to_text, jsonld
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
# A refusal the site makes to us: the archive only with the user's consent (D-0001).
BLOCK_STATUS = {"403"}
BLOCK_PROBLEMS = {"blocked_by_challenge"}
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
                                      timeout=getattr(crawler, "deadline", crawler.timeout * 3))
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


def _github(run, crawler, idx, url) -> dict | None:
    """S-source-acquisition-045: a GitHub link read from its raw Markdown; None to go on."""
    raw = github_raw(url)
    if not raw:
        return None
    try:
        r = crawler.fetch(raw, types=("text/plain", "text/markdown"))
    except FetchError as e:
        if e.reason in NO_FALLBACK:
            raise
        return None
    md = html_blocks_to_text(r.body.decode("utf-8", "replace"))
    cand = _candidate(md, [], first_heading(md) or url, r.body, f"D{idx}.md", redact(url),
                      via="github_readme")
    alt = _accept(run, idx, cand, 0)
    return dict(alt, final_url=redact(url), hops=[redact(raw)]) if alt else None


def _jsonld_body(idx, res, title):
    """S-source-acquisition-048: the page's own JSON-LD articleBody, for a thin page only."""
    ld = jsonld(res.body.decode("utf-8", "replace"))
    if not ld.get("body"):
        return None
    return _candidate(ld["body"], [], ld.get("title") or title, res.body, f"D{idx}.jsonld.html",
                      redact(res.final_url), via="jsonld")


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


class BlockedError(FetchError):
    """The site refused us; archive_at is the date of a Wayback copy the user may choose."""

    def __init__(self, reason: str, detail: str, archive_at: str | None):
        super().__init__(reason, detail)
        self.archive_at = archive_at


def _archive_lookup(crawler, url) -> str | None:
    """The newest snapshot's timestamp, asked of archive.org only (never the site). A URL
    carrying secrets is never sent: it would leak them, and could not be archived anyway."""
    if _profile(crawler, url).get("no_archive") or redact(url) != url:
        return None
    try:
        api = crawler.fetch(ARCHIVE_API + quote(url, safe=""), types=("application/json",))
        snap = json.loads(api.body.decode("utf-8")).get("archived_snapshots", {}).get("closest")
        if not snap or not snap.get("available") or str(snap.get("status", "200")) != "200":
            return None
        ts = str(snap["timestamp"])
    except (FetchError, ValueError, KeyError, AttributeError, TypeError):
        return None
    return ts if re.fullmatch(r"\d{8,14}", ts) else None


def _date(ts: str) -> str:
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"


def _blocked(crawler, url, reason: str, detail: str) -> BlockedError:
    ts = _archive_lookup(crawler, url)
    return BlockedError(reason, detail, _date(ts) if ts else None)


def _archive(crawler, idx, url):
    """The newest Wayback Machine snapshot, fetched through the same safe crawler."""
    ts = _archive_lookup(crawler, url)
    if not ts:
        return None
    try:
        r = crawler.fetch(f"https://web.archive.org/web/{ts}id_/{url}")
        md, hidden, title, ext, problem = _convert(r)
    except (FetchError, ConvertError, ValueError, KeyError, AttributeError, TypeError):
        return None
    if problem or not md.strip():
        return None
    human = f"https://web.archive.org/web/{ts}/{url}"
    return _candidate(md, hidden, title or url, r.body, f"D{idx}.archive.{ext}", human,
                      via="archive", archived_at=_date(ts),
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


def _fetch_item(run: Run, crawler: Crawler, idx: int, url: str, renderer=None,
                archive_on_block: bool = False) -> dict:
    """D-0001 order: crawler (with bounded retries) -> browser for thin, empty or needs_js
    pages -> AMP -> archive. The paste step is offered by the sources phase."""
    profile = _profile(crawler, url)
    start, budget = time.monotonic(), getattr(crawler, "url_budget", 90.0)

    def spent() -> bool:   # S-source-acquisition-044: no further fallback past the budget
        return time.monotonic() - start >= budget

    gh = _github(run, crawler, idx, url)
    if gh:
        return gh
    try:
        res = crawler.fetch(url)
    except FetchError as e:
        if e.reason in NO_FALLBACK or (e.reason == "http_status" and e.detail in NO_FALLBACK_STATUS):
            raise
        if e.reason == "http_status" and e.detail in BLOCK_STATUS and not archive_on_block:
            raise _blocked(crawler, url, e.reason, e.detail)
        if spent():
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
    if problem in BLOCK_PROBLEMS and not archive_on_block:
        raise _blocked(crawler, url, problem, redact(res.final_url))
    if problem and problem not in THIN_PROBLEMS:
        alt = _accept(run, idx, _archive(crawler, idx, url), 0) if not spent() else None
        if alt:
            return dict(alt, fell_back_from=problem)
        raise FetchError(problem, redact(res.final_url))
    base = {"final_url": redact(res.final_url), "hops": [redact(h) for h in res.hops]}
    _store_raw(run, f"D{idx}.{ext}", res.body)  # the original stays, whatever replaces it
    live = len(md.strip())
    thin = ext == "html" and (problem is not None or live < THIN_PAGE_CHARS)
    over_budget = False
    if ext == "html" and (thin or profile.get("needs_js")):
        steps = []
        if thin:   # cheap, and only standing in for a page that yields too little text
            steps.append(lambda: _jsonld_body(idx, res, title))
        if renderer is not None:
            steps.append(lambda: _rendered(crawler, renderer, idx, res.final_url, title))
        if thin:
            steps += [lambda: _amp(crawler, idx, res, title),
                      lambda: _archive(crawler, idx, url)]
        for step in steps:
            if spent():
                over_budget = True
                break
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
    if over_budget:
        item["warning"] = "; ".join(x for x in (item.get("warning"), "url_budget_exceeded") if x)
    return item


# S-source-acquisition-054: an RSS series converted to one file ("---", "## title", "url  (date)")
SERIES_ITEM = re.compile(r"^---[ \t]*\n## (.+?)[ \t]*\n(https?://\S+)[ \t]+\((\d{4}-\d\d-\d\d)[^)\n]*\)[ \t]*\n",
                         re.M)


def split_series(md: str) -> list[dict]:
    """[{title, url, date, body}] when the text holds two or more series items, else []."""
    hits = list(SERIES_ITEM.finditer(md))
    if len(hits) < 2:
        return []
    ends = [h.start() for h in hits[1:]] + [len(md)]
    return [{"title": h.group(1).strip(), "url": h.group(2), "date": h.group(3),
             "body": md[h.end():e].strip()} for h, e in zip(hits, ends)]


def _series_docs(run: Run, idx: int, md: str) -> dict | None:
    items = split_series(md)
    if not items:
        return None
    recs = []
    for k, it in enumerate(items, 1):
        doc_id = f"D{idx}-{k}"
        rec = _doc_record(run, doc_id, redact(it["url"]), it["title"], it["body"],
                          it["body"].encode("utf-8"), f"{doc_id}.md", [])
        rec["date"] = it["date"]
        recs.append(rec)
    return {"docs": recs, "series": len(recs)}


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
    series = _series_docs(run, idx, d.markdown)
    if series:
        _store_raw(run, f"D{idx}{p.suffix or '.txt'}", d.raw)   # the file as given stays
        return series
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
    series = _series_docs(run, idx, value)
    if series:
        _store_raw(run, f"D{idx}.txt", value.encode("utf-8"))
        return series
    doc_id = f"D{idx}"
    first = value.strip().splitlines()[0].lstrip("#").strip()[:60] if value.strip() else "text"
    item = {"docs": [_doc_record(run, doc_id, redact(pasted_for), first, value.strip(),
                                 value.encode("utf-8"), f"{doc_id}.txt", [])]}
    if pasted_for:
        item["via"] = "paste"
    return item


def run_sources(run: Run, crawler: Crawler, *, on_progress=None, renderer=None,
                archive_on_block: bool | set[int] = False) -> dict:
    """archive_on_block: True for every item, or the item numbers the user agreed for."""
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
                consent = archive_on_block is True or (isinstance(archive_on_block, set)
                                                       and idx in archive_on_block)
                entry.update(_fetch_item(run, crawler, idx, target["value"], renderer, consent))
            elif target["kind"] == "feed_item":
                entry.update(_feed_item(run, crawler, idx, target, renderer))
            elif target["kind"] == "path":
                entry.update(_path_item(run, idx, target["value"]))
            else:
                entry.update(_text_item(run, idx, target["value"], target.get("pasted_for", "")))
            entry["status"] = "ok"
        except (FetchError, ConvertError) as e:
            entry.update(status="failed", reason=e.reason, detail=redact(str(e))[:300])
            if isinstance(e, BlockedError):
                entry.update(blocked=True, archive_at=e.archive_at)
        items.append(entry)
        if on_progress:
            on_progress(entry)
    manifest = {"items": items, "cited": _cited(run, crawler, intake, manifest.get("cited", []))}
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


MAX_CITED = 3
# A URL in pasted text ends at the first CJK character or full-width mark: "…/2610.37741这篇论文"
# is the paper's URL followed by prose, never one path (a copied Chinese path is %-encoded).
_CITED_RE = re.compile(r"https?://[^\s<>\"'，。、；：！？「」『』（）()\[\]⺀-鿿豈-﫿＀-￯]+",
                       re.I)


def cited_urls(intake: dict) -> list[str]:
    """S-source-acquisition-050: URLs written inside text targets, not already targets."""
    from ..factcheck import norm_url
    seen = {norm_url(t["value"]) for t in intake["targets"] if t["kind"] in ("url", "feed_item")}
    out = []
    for t in intake["targets"]:
        if t["kind"] != "text":
            continue
        for u in _CITED_RE.findall(t["value"]):
            u = u.rstrip(".,;:!?")
            n = norm_url(u)
            if n and n not in seen:
                seen.add(n)
                out.append(u)
    return out[:MAX_CITED]


def _cited(run: Run, crawler: Crawler, intake: dict, prior: list[dict]) -> list[dict]:
    """Each cited URL fetched once into 01-sources/cited/R<n>.md: a reference for the
    fact-check and the share analysis, never a document under review. No fallbacks and no
    questions: a failure is recorded and the run goes on."""
    if crawler is None:        # text-only runs in tests: nothing to fetch with
        return []
    done = {c["url"]: c for c in prior if c.get("status") == "ok"}
    out = []
    for n, url in enumerate(cited_urls(intake), 1):
        if url in done and run.path(done[url]["file"]).exists():
            out.append(done[url])
            continue
        rid, entry = f"R{n}", {"url": redact(url)}
        try:
            raw = github_raw(url)
            if raw:
                res = crawler.fetch(raw, types=("text/plain", "text/markdown"))
                md, title, ext = html_blocks_to_text(res.body.decode("utf-8", "replace")), "", "md"
                title = first_heading(md)
            else:
                res = crawler.fetch(url)
                if res.content_type in FEED_TYPES:
                    raise FetchError("is_feed", redact(url))
                md, _, title, ext, problem = _convert(res)
                if problem:
                    raise FetchError(problem, redact(res.final_url))
            file = f"01-sources/cited/{rid}.md"
            _store_raw(run, f"{rid}.{ext}", res.body)
            write_text_atomic(run.path(file), md.strip() + "\n")
            entry.update(id=rid, status="ok", file=file, title=title or redact(url),
                         chars=len(md.strip()))
        except (FetchError, ConvertError) as e:
            entry.update(id=rid, status="failed", reason=e.reason)
        out.append(entry)
    return out


def cited_sources(run: Run) -> list[dict]:
    """The cited sources that were read, with their text."""
    m = read_json(run.path("01-sources/manifest.json"), default={})
    return [dict(c, text=run.path(c["file"]).read_text(encoding="utf-8"))
            for c in m.get("cited", []) if c.get("status") == "ok" and run.path(c["file"]).exists()]


def failed_items(manifest: dict) -> list[dict]:
    return [it for it in manifest.get("items", []) if it.get("status") != "ok"]

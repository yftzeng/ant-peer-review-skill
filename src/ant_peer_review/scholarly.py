"""Opt-in academic identifier checks (K-Dense paper-lookup): DOIs and arXiv ids in
the piece are resolved against doi.org, Crossref and arXiv, deterministically.

Only runs when the run's intake has fact_sources ["academic"]. Results go into
the fact-check ledger as type "citation"; the model checker never handles them.
Every API answer is untrusted data and its shape is checked, because these
services can fail with HTTP 200 (arXiv answers an unknown id with an empty feed).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import quote
from xml.etree import ElementTree

from .factcheck import RETRYABLE, read_ledger, write_ledger
from .jsonio import read_json
from .sources.crawler import Crawler, FetchError
from .workspace import Run

MAX_IDS = 30
API_TYPES = ("application/json", "application/atom+xml", "application/xml", "text/xml")
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>，。、；：！？」』）】]+)", re.I)
ARXIV_RE = re.compile(r"(?:\barxiv:\s?|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
QUOTED_TITLE = re.compile(r"[“\"「『]([^”\"」』]{8,200})[”\"」』]")
ATOM = "{http://www.w3.org/2005/Atom}"
RETRACTION_TYPES = {"retraction", "withdrawal", "removal"}


def enabled(run: Run) -> bool:
    return "academic" in read_json(run.path("00-intake.json"), default={}).get("fact_sources", [])


def api_crawler() -> Crawler:
    # Documented public APIs: robots.txt is for crawlers of pages, not API clients.
    return Crawler(respect_robots=False, allowed_types=API_TYPES,
                   host_intervals={"export.arxiv.org": 3.0})  # arXiv: 1 request / 3 s


def _clean_doi(raw: str) -> str:
    doi = raw.rstrip(".,;:")
    while doi.endswith(")") and doi.count("(") < doi.count(")"):
        doi = doi[:-1]
    return doi


def extract(run: Run) -> list[dict]:
    """[{ident, kind, value, anchor, sentence}] in document order, deduplicated, capped."""
    segs = read_json(run.path("01-sources/segments.json"), default={})
    found, seen = [], set()
    for doc in segs.values():
        for seg in doc:
            units = seg["sentences"] or [{"id": seg["id"], "text": seg["text"]}]
            for s in units:
                for m in DOI_RE.finditer(s["text"]):
                    doi = _clean_doi(m.group(1))
                    if doi.lower() not in seen:
                        seen.add(doi.lower())
                        found.append({"ident": doi, "kind": "doi", "value": doi,
                                      "anchor": s["id"], "sentence": s["text"]})
                for m in ARXIV_RE.finditer(s["text"]):
                    aid = m.group(1)
                    if f"arxiv:{aid}" not in seen:
                        seen.add(f"arxiv:{aid}")
                        found.append({"ident": f"arXiv:{aid}", "kind": "arxiv", "value": aid,
                                      "anchor": s["id"], "sentence": s["text"]})
    return found[:MAX_IDS]


def _json(crawler, url: str) -> dict:
    res = crawler.fetch(url)
    try:
        return json.loads(res.body.decode("utf-8", "replace"))
    except ValueError:
        raise FetchError("bad_api_response", url)


def _year(msg: dict) -> str:
    parts = (msg.get("issued") or msg.get("published") or {}).get("date-parts") or [[]]
    return str(parts[0][0]) if parts and parts[0] else ""


def check_doi(crawler, item: dict) -> dict:
    doi = item["value"]
    link = f"https://doi.org/{doi}"
    try:
        handle = _json(crawler, f"https://doi.org/api/handles/{quote(doi, safe='/')}")
    except FetchError as e:
        if e.reason == "http_status" and e.detail.startswith("404"):
            return {"status": "unsupported", "reason": "identifier_not_found", "sources": []}
        raise
    if handle.get("responseCode") != 1:
        return {"status": "unsupported", "reason": "identifier_not_found", "sources": []}
    try:
        msg = _json(crawler, f"https://api.crossref.org/works/{quote(doi, safe='/')}").get("message", {})
    except FetchError as e:
        if e.reason == "http_status" and e.detail.startswith("404"):  # e.g. a DataCite DOI
            return {"status": "supported", "reason": "resolves; no Crossref record",
                    "sources": [{"url": link, "supporting_excerpt": "doi.org: DOI resolves"}]}
        raise
    title = " ".join(msg.get("title") or []).strip()
    excerpt = f"Crossref: {title} ({_year(msg)})".strip()
    src = [{"url": link, "supporting_excerpt": excerpt}]
    retracted = any(u.get("type", "").lower() in RETRACTION_TYPES
                    for u in msg.get("updated-by") or []) or title.upper().startswith("RETRACTED")
    if retracted:
        return {"status": "unsupported", "reason": "retracted", "sources": src}
    quoted = QUOTED_TITLE.search(item["sentence"])
    if quoted and title:
        ratio = SequenceMatcher(None, quoted.group(1).lower(), title.lower()).ratio()
        if ratio < 0.6:
            return {"status": "partly", "reason": "title_mismatch", "sources": src}
    return {"status": "supported", "reason": "", "sources": src}


def check_arxiv(crawler, item: dict) -> dict:
    aid = item["value"]
    res = crawler.fetch(f"https://export.arxiv.org/api/query?id_list={aid}")
    try:
        root = ElementTree.fromstring(res.body)
    except ElementTree.ParseError:
        raise FetchError("bad_api_response", aid)
    entries = root.findall(f"{ATOM}entry")
    title = (entries[0].findtext(f"{ATOM}title") or "").strip() if entries else ""
    if not entries or title.lower() == "error":
        return {"status": "unsupported", "reason": "identifier_not_found", "sources": []}
    year = (entries[0].findtext(f"{ATOM}published") or "")[:4]
    return {"status": "supported", "reason": "",
            "sources": [{"url": f"https://arxiv.org/abs/{aid}",
                         "supporting_excerpt": f"arXiv: {' '.join(title.split())} ({year})"}]}


def verify_identifiers(run: Run, crawler=None, *, say=lambda *_: None) -> list[dict]:
    """Add/refresh citation claims; only pending or retryable ones are queried."""
    if not enabled(run):
        return []
    crawler = crawler or api_crawler()
    ledger = read_ledger(run)
    by_ident = {c.get("ident"): c for c in ledger if c["type"] == "citation"}
    n = sum(1 for c in ledger if c["type"] == "citation")
    for item in extract(run):
        c = by_ident.get(item["ident"])
        if c is None:
            n += 1
            c = {"id": f"R{n:02d}", "anchor": item["anchor"], "type": "citation",
                 "ident": item["ident"], "text": f"Cites {item['ident']}", "status": "pending",
                 "reason": "", "sources": [], "extracted_by": ["identifier-scan"], "refs": [],
                 "checked_by": "", "updated_at": ""}
            ledger.append(c)
            by_ident[item["ident"]] = c
        if c["status"] != "pending" and not (c["status"] == "cannot_verify"
                                             and c.get("reason") in RETRYABLE):
            continue
        now = datetime.now().isoformat(timespec="seconds")
        try:
            out = (check_doi if item["kind"] == "doi" else check_arxiv)(crawler, item)
        except FetchError as e:
            reason = e.reason if e.reason in ("timeout",) else (
                "offline" if e.reason in ("network", "dns") else "error")
            out = {"status": "cannot_verify", "reason": reason, "sources": []}
        c.update(out, checked_by="doi.org+crossref" if item["kind"] == "doi" else "arxiv",
                 updated_at=now)
        c["sources"] = [dict(s, accessed_at=now) for s in c["sources"]]
        say(f"  … {c['id']} {item['ident']} → {c['status']}"
            + (f" ({c['reason']})" if c["reason"] else ""))
        write_ledger(run, ledger)
    return [c for c in ledger if c["type"] == "citation"]

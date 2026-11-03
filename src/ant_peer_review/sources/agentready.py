"""Forms of a page meant for programs, read before the page itself is parsed.

- A GitHub repository or file link maps to its raw Markdown on raw.githubusercontent.com
  (github.com's robots.txt disallows /raw/ and /tree/; the raw host has none).
- Requests ask for Markdown first: sites that serve Markdown to agents answer with it.
- JSON-LD (schema.org) gives the title, author, date and publisher. Its articleBody can
  differ from what readers see, so it only stands in for a page that yields too little
  text, and is labelled as such."""
from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urlsplit

ARTICLE_TYPES = {"article", "newsarticle", "blogposting", "techarticle", "scholarlyarticle",
                 "report", "analysisnewsarticle", "opinionnewsarticle", "reportagenewsarticle",
                 "socialmediaposting", "creativework"}
_LD_RE = re.compile(r"<script\b[^>]*type=[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script>",
                    re.I | re.S)
_SEG = re.compile(r"^[A-Za-z0-9_.-]+$")


def github_raw(url: str) -> str | None:
    """github.com/o/r[/] -> README at HEAD; /blob/<ref>/<path> -> that file; /tree/<ref>/<dir>
    -> the README in it. Anything else: None."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != "https" or (parts.hostname or "").lower() not in ("github.com",
                                                                           "www.github.com"):
        return None
    segs = [s for s in parts.path.split("/") if s]
    if len(segs) < 2 or not all(_SEG.match(s) for s in segs):
        return None
    owner, repo = segs[0], segs[1].removesuffix(".git")
    base = f"https://raw.githubusercontent.com/{owner}/{repo}"
    if len(segs) == 2:
        return f"{base}/HEAD/README.md"
    if len(segs) >= 4 and segs[2] == "blob" and segs[-1].lower().endswith((".md", ".markdown")):
        return f"{base}/{'/'.join(segs[3:])}"
    if len(segs) >= 4 and segs[2] == "tree":
        return f"{base}/{'/'.join(segs[3:])}/README.md"
    return None


_HTML_BLOCK = re.compile(r"^\s*<(?:[a-zA-Z][a-zA-Z0-9]*|!--)")


def html_blocks_to_text(md: str) -> str:
    """Markdown with raw HTML blocks (GitHub READMEs: centred logos, badges, <h1>): each
    such block becomes its text; code fences stay as written."""
    from .htmlmd import html_to_markdown
    out, fence = [], False
    for block in re.split(r"\n\s*\n", md):
        if block.lstrip().startswith(("```", "~~~")) or fence:
            fence ^= block.count("```") % 2 == 1 or block.count("~~~") % 2 == 1
            out.append(block)
        elif _HTML_BLOCK.match(block):
            text = html_to_markdown(f"<div>{block}</div>").markdown.strip()
            if text:
                out.append(text)
        else:
            out.append(block)
    return "\n\n".join(out)


def first_heading(md: str) -> str:
    m = re.search(r"^#{1,3}\s+(.+?)\s*#*\s*$", md, re.M)
    return m.group(1).strip() if m else ""


def accept_header(types: tuple[str, ...]) -> str:
    """Markdown first when it is acceptable at all; the rest at q=0.9."""
    if "text/markdown" not in types:
        return ", ".join(types)
    return ", ".join(["text/markdown"] + [f"{t};q=0.9" for t in types if t != "text/markdown"])


def _nodes(data) -> list[dict]:
    out: list[dict] = []
    stack = [data]
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            stack.extend(reversed(x))
        elif isinstance(x, dict):
            out.append(x)
            if "@graph" in x:
                stack.append(x["@graph"])
    return out


def _name(v) -> str:
    if isinstance(v, list):
        return ", ".join(n for n in (_name(x) for x in v) if n)
    if isinstance(v, dict):
        return str(v.get("name") or "").strip()
    return str(v or "").strip()


def jsonld(html: str) -> dict:
    """The first article-like JSON-LD node: title, author, date, organization, body.
    Broken or missing JSON-LD gives {}."""
    for m in _LD_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        for n in _nodes(data):
            types = n.get("@type")
            types = types if isinstance(types, list) else [types]
            if not any(str(t).lower() in ARTICLE_TYPES for t in types if t):
                continue
            return {"title": unescape(str(n.get("headline") or n.get("name") or "")).strip()[:300],
                    "author": unescape(_name(n.get("author")))[:200],
                    "date": str(n.get("datePublished") or "")[:10],
                    "organization": unescape(_name(n.get("publisher")))[:200],
                    "body": str(n.get("articleBody") or "").strip()}
    return {}

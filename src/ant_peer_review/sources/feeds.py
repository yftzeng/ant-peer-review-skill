"""RSS 2.0 / Atom feeds: list the articles with their full HTML from the feed itself.

Parsed with ElementTree (expat refuses entity amplification); items capped.
Feed text is untrusted like any page: it goes through htmlmd and the injection scan.
"""
from __future__ import annotations

from xml.etree import ElementTree

MAX_ITEMS = 100
CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
ATOM = "{http://www.w3.org/2005/Atom}"
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/xml", "text/xml",
              "application/rdf+xml")


def _text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def parse_feed(body: bytes) -> list[dict]:
    """[{title, link, date, html}] in feed order. ValueError if it is not RSS or Atom."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as e:
        raise ValueError(f"not a feed: {e}")
    items: list[dict] = []
    channel = root.find("channel")
    if root.tag == "rss" or channel is not None:
        container = channel if channel is not None else root
        for it in container.findall("item")[:MAX_ITEMS]:
            html = _text(it.find(CONTENT_NS)) or _text(it.find("description"))
            items.append({"title": _text(it.find("title")) or "(untitled)",
                          "link": _text(it.find("link")) or _text(it.find("guid")),
                          "date": _text(it.find("pubDate")), "html": html})
        return items
    if root.tag == f"{ATOM}feed":
        for e in root.findall(f"{ATOM}entry")[:MAX_ITEMS]:
            link = ""
            for ln in e.findall(f"{ATOM}link"):
                if ln.get("rel", "alternate") == "alternate":
                    link = ln.get("href", "")
                    break
            html = _text(e.find(f"{ATOM}content")) or _text(e.find(f"{ATOM}summary"))
            items.append({"title": _text(e.find(f"{ATOM}title")) or "(untitled)", "link": link,
                          "date": _text(e.find(f"{ATOM}updated")) or _text(e.find(f"{ATOM}published")),
                          "html": html})
        return items
    raise ValueError(f"not a feed: root element {root.tag!r}")

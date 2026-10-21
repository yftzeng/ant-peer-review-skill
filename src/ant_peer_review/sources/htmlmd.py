"""HTML -> Markdown with hidden content separated out (stdlib html.parser).

Visible text goes to Markdown. Text a reader would not see (script/style,
display:none, hidden, aria-hidden, zero font size, comments) and attribute text
(alt/title/aria-label) goes to `hidden` so the injection scan can inspect it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "object", "head"}
CHROME_TAGS = {"nav", "footer", "aside", "form"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "header", "li", "blockquote", "pre",
              "tr", "table", "ul", "ol", "figure", "figcaption", "dd", "dt", "h1", "h2", "h3",
              "h4", "h5", "h6", "br", "hr"}
VOID = {"br", "hr", "img", "meta", "link", "input", "source", "wbr", "area", "base", "col"}
HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.\d]*[1-9])|"
    r"opacity\s*:\s*0(?:\.0*)?\s*(?:;|$)|color\s*:\s*(?:#fff(?:fff)?|white)\b", re.I)


@dataclass
class Converted:
    title: str
    markdown: str
    hidden: list[dict] = field(default_factory=list)  # {"kind", "text"}


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []   # (tag, hides_content)
        self.blocks: list[str] = []
        self.buf: list[str] = []
        self.prefix = ""
        self.hidden: list[dict] = []
        self.hidden_buf: list[str] = []
        self.title = ""
        self._in_title = False
        self._hidden_depth = 0

    # helpers
    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        if text:
            self.blocks.append(self.prefix + text)
        self.buf = []
        self.prefix = ""

    def _flush_hidden(self, kind: str):
        text = re.sub(r"\s+", " ", "".join(self.hidden_buf)).strip()
        if text:
            self.hidden.append({"kind": kind, "text": text})
        self.hidden_buf = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        for k in ("alt", "title", "aria-label"):
            if a.get(k):
                self.hidden.append({"kind": f"attr:{k}", "text": a[k]})
        if tag == "title":
            self._in_title = True
        hides = (tag in SKIP_TAGS or tag in CHROME_TAGS or "hidden" in a
                 or a.get("aria-hidden", "").lower() == "true"
                 or bool(HIDDEN_STYLE.search(a.get("style", ""))))
        if tag in VOID:
            if tag in ("br", "hr") and not self._hidden_depth:
                self._flush()
            return
        if hides:
            if not self._hidden_depth:
                self._flush()
            self._hidden_depth += 1
        self.stack.append((tag, hides))
        if self._hidden_depth:
            return
        if tag in BLOCK_TAGS:
            self._flush()
            if re.fullmatch(r"h[1-6]", tag):
                self.prefix = "#" * int(tag[1]) + " "
            elif tag == "li":
                self.prefix = "- "
            elif tag == "blockquote":
                self.prefix = "> "

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in VOID:
            return
        # pop to the matching tag (tolerate unclosed children)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for t, hides in reversed(self.stack[i:]):
                    if hides:
                        self._hidden_depth -= 1
                        if not self._hidden_depth:
                            kind = "chrome" if t in CHROME_TAGS else (
                                "script_style" if t in SKIP_TAGS else "hidden_element")
                            self._flush_hidden(kind)
                del self.stack[i:]
                break
        if not self._hidden_depth and tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._hidden_depth:
            self.hidden_buf.append(data)
        else:
            self.buf.append(data)

    def handle_comment(self, data):
        if data.strip():
            self.hidden.append({"kind": "comment", "text": data.strip()})

    def close(self):
        super().close()
        self._flush()


def _main_region(html: str) -> str:
    for tag in ("article", "main"):
        m = re.search(rf"<{tag}\b[^>]*>.*?</{tag}>", html, re.S | re.I)
        if m:
            return m.group(0)
    return html


def html_to_markdown(html: str) -> Converted:
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    p = _Parser()
    p.feed(_main_region(html))
    p.close()
    # Comments and hidden parts outside the main region are still worth scanning.
    if _main_region(html) is not html:
        outer = _Parser()
        outer.feed(html)
        outer.close()
        seen = {(h["kind"], h["text"]) for h in p.hidden}
        p.hidden += [h for h in outer.hidden if (h["kind"], h["text"]) not in seen
                     and h["kind"] != "chrome"]
    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""
    md = "\n\n".join(p.blocks)
    return Converted(title=title, markdown=md, hidden=p.hidden)

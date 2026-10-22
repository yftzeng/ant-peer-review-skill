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
# Class/id words that mark the article body when a page has no <article>/<main>.
CONTENT_HINT = re.compile(r"(?:^|[\s_-])(?:markdown|article|post|entry|content|story|prose)"
                          r"(?:$|[\s_-])", re.I)
MIN_CANDIDATE_CHARS = 200
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
        self.textlen = 0                 # visible characters so far
        self.open_cands: dict[int, tuple[int, int]] = {}   # stack index -> (block, textlen)
        self.candidates: list[tuple[int, int, int, int]] = []  # (textlen, depth, start, end)

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
            if tag in ("div", "section") and (CONTENT_HINT.search(a.get("class", ""))
                                              or CONTENT_HINT.search(a.get("id", ""))):
                self.open_cands[len(self.stack) - 1] = (len(self.blocks), self.textlen)
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
        closed = []
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                closed = [j for j in self.open_cands if j >= i]
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
        for j in closed:
            start, t0 = self.open_cands.pop(j)
            self.candidates.append((self.textlen - t0, j, start, len(self.blocks)))

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._hidden_depth:
            self.hidden_buf.append(data)
        else:
            self.buf.append(data)
            self.textlen += len(data.strip())

    def handle_comment(self, data):
        if data.strip():
            self.hidden.append({"kind": "comment", "text": data.strip()})

    def close(self):
        super().close()
        self._flush()


def _find_element(html: str, lower: str, tag: str) -> tuple[int, int, int] | None:
    """(start, inner_start, end) of the first <tag ...>...</tag>, found with str.find
    so hostile input cannot trigger regex backtracking."""
    pos = 0
    while True:
        i = lower.find(f"<{tag}", pos)
        if i < 0:
            return None
        nxt = lower[i + len(tag) + 1:i + len(tag) + 2]
        if nxt and (nxt.isalnum() or nxt in "-_"):
            pos = i + 1
            continue
        gt = lower.find(">", i)
        if gt < 0:
            return None
        j = lower.find(f"</{tag}>", gt)
        if j < 0:
            return None
        return i, gt + 1, j + len(tag) + 3


def _main_region(html: str) -> str:
    lower = html.lower()
    for tag in ("article", "main"):
        hit = _find_element(html, lower, tag)
        if hit:
            return html[hit[0]:hit[2]]
    return html


def html_to_markdown(html: str) -> Converted:
    t_hit = _find_element(html, html.lower(), "title")
    p = _Parser()
    p.feed(_main_region(html))
    p.close()
    # Comments and hidden parts outside the main region are still worth scanning.
    if len(_main_region(html)) != len(html):
        outer = _Parser()
        outer.feed(html)
        outer.close()
        seen = {(h["kind"], h["text"]) for h in p.hidden}
        p.hidden += [h for h in outer.hidden if (h["kind"], h["text"]) not in seen
                     and h["kind"] != "chrome"]
    title = " ".join(html[t_hit[1]:t_hit[2] - len("</title>")].split()) if t_hit else ""
    blocks = p.blocks
    if len(_main_region(html)) == len(html):
        # No <article>/<main>: the innermost content-like container that still holds
        # most (>= 80%) of the text of the largest one, so wrappers with share
        # buttons and view counters lose to the article body inside them.
        good = [c for c in p.candidates if c[0] >= MIN_CANDIDATE_CHARS and c[3] > c[2]]
        if good:
            top = max(c[0] for c in good)
            _, _, start, end = max((c for c in good if c[0] >= 0.8 * top),
                                   key=lambda c: (c[1], c[0]))
            blocks = p.blocks[start:end]
    md = "\n\n".join(blocks)
    return Converted(title=title, markdown=md, hidden=p.hidden)

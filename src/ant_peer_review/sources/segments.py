"""Stable paragraph / sentence ids: D<doc>.P<nn>.S<n>.

Headings are their own paragraph without sentence ids. The prompt view wraps
every sentence with its id so reviewers can anchor findings precisely.
"""
from __future__ import annotations

import re
import unicodedata

_SENT = re.compile(r"(?<=[。！？!?；;])\s*|(?<=[.])\s+(?=[A-Z0-9\"'“‘(（一-鿿])")


def split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENT.split(text) if s and s.strip()]
    return parts or [text.strip()]


def segment(markdown: str, doc: int) -> list[dict]:
    """Return [{"id", "kind": "heading"|"para", "text", "sentences": [{"id","text"}]}]."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", markdown) if b.strip()]
    out = []
    for i, block in enumerate(blocks, 1):
        pid = f"D{doc}.P{i:02d}"
        if block.startswith("#"):
            out.append({"id": pid, "kind": "heading", "text": block, "sentences": []})
            continue
        flat = re.sub(r"\s*\n\s*", " ", block)
        sents = [{"id": f"{pid}.S{j}", "text": s}
                 for j, s in enumerate(split_sentences(flat), 1)]
        out.append({"id": pid, "kind": "para", "text": flat, "sentences": sents})
    return out


def all_ids(segs: list[dict]) -> list[str]:
    ids = []
    for s in segs:
        if s["kind"] == "heading":
            ids.append(s["id"])
        else:
            ids.extend(x["id"] for x in s["sentences"])
    return ids


def prompt_view(segs: list[dict], withheld: dict[str, str] | None = None) -> str:
    """Render segments for a prompt. Paragraph ids in `withheld` map to a flag id
    and are replaced by a marker instead of their text."""
    withheld = withheld or {}
    lines = []
    for s in segs:
        if s["id"] in withheld:
            lines.append(f"[{s['id']}] ⟨withheld: flagged as possible prompt injection "
                         f"{withheld[s['id']]}⟩")
        elif s["kind"] == "heading":
            lines.append(f"[{s['id']}] {s['text']}")
        else:
            lines.append(" ".join(f"[{x['id']}] {x['text']}" for x in s["sentences"]))
    text = "\n\n".join(lines)
    # Strip zero-width / bidi controls; the scan already recorded them.
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")

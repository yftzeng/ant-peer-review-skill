"""Prompt-injection scan over visible paragraphs and hidden spans.

Categories follow OWASP LLM01:2025, Greshake et al. 2023 and the 2025 reports of
hidden prompts in preprints: anything that asks a reviewer/LLM for an identifiable
output, a score, a direction, priority over instructions, secrecy, or tool/data
actions is a candidate. Matches are
flags with a category and confidence, not verdicts.
"""
from __future__ import annotations

import re
import unicodedata

CATEGORIES = {
    "rating_manipulation": [
        r"\b(?:give|rate|score|grade)\b[^.\n]{0,40}\b(?:10/10|\d+\s*/\s*\d+|full marks|5 stars|"
        r"highest|perfect|accept)\b",
        r"(?:給|打|評)[^。\n]{0,10}(?:滿分|高分|10\s*分|五星)", r"(?:给|打|评)[^。\n]{0,10}(?:满分|高分|10\s*分|五星)",
    ],
    "sentiment_steering": [
        r"\b(?:only (?:praise|positive)|do not (?:criticize|mention (?:any )?weakness))",
        r"(?:只(?:能|准)?(?:稱讚|称赞|說好話|说好话)|不(?:要|得)(?:批評|批评|指出缺點|指出缺点))",
    ],
    "output_dictation": [
        r"\b(?:must include|include the (?:exact )?phrase|end (?:your|the) (?:review|answer) with|"
        r"start (?:your|the) (?:review|answer) with)\b",
        r"(?:必須包含|必须包含|以此結尾|以此结尾|請在(?:回答|評語)中加入)",
    ],
    "canary_check": [
        r"\b(?:canary|watermark|verification phrase|confirm you (?:have )?read)\b",
        r"(?:確認已讀|确认已读|暗號|暗号)",
    ],
    "instruction_override": [
        r"\b(?:ignore|disregard|forget)\b[^.\n]{0,30}\b(?:previous|prior|above|earlier|all)\b"
        r"[^.\n]{0,20}\b(?:instructions?|prompts?|rules?)\b",
        r"\b(?:system prompt|developer message|you are now|new instructions?|override)\b",
        r"(?:忽略|無視|无视)[^。\n]{0,10}(?:之前|以上|先前|所有)[^。\n]{0,6}(?:指令|指示|規則|规则)",
        r"</?(?:system|assistant|instructions?)>",
    ],
    "addressed_to_ai": [
        r"\b(?:(?:ai|llm|language model|reviewer|grader|assistant|chatgpt|claude)s?\b[^.\n]{0,30}"
        r"\b(?:should|must|reading this))",
        r"(?:審稿人|审稿人|AI|大模型|語言模型|语言模型)[^。\n]{0,10}(?:請|请|必須|必须|應該|应该)",
    ],
    "secrecy_request": [
        r"\b(?:do not (?:disclose|reveal|tell|mention)|silently|without telling|keep this secret)\b",
        r"(?:不要告訴|不要告诉|不要透露|勿告知|保密)",
    ],
    "action_request": [
        r"\b(?:visit|open|fetch|send|post|upload|exfiltrate)\b[^.\n]{0,30}\bhttps?://",
        r"\b(?:run|execute)\b[^.\n]{0,20}\b(?:code|command|script|shell)\b",
    ],
}
_COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in CATEGORIES.items()}
HIGH = {"instruction_override", "rating_manipulation", "secrecy_request", "sentiment_steering", "action_request"}


def format_controls(text: str) -> list[str]:
    """Unicode Cf characters (zero-width, bidi overrides…), excluding a BOM at 0."""
    found = []
    for i, ch in enumerate(text):
        if unicodedata.category(ch) == "Cf" and not (i == 0 and ch == "﻿"):
            found.append(f"U+{ord(ch):04X}")
    return found


def search_view(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")
    return re.sub(r"\s+", " ", t)


def categorize(text: str) -> list[str]:
    view = search_view(text)
    return [cat for cat, pats in _COMPILED.items() if any(p.search(view) for p in pats)]


def scan(segments: list[dict], hidden: list[dict]) -> dict:
    """Return {"flags": [...], "withheld": {paragraph_id: flag_id}}."""
    flags: list[dict] = []
    withheld: dict[str, str] = {}

    def add(location: str, kind: str, cats: list[str], excerpt: str, cf: list[str]):
        fid = f"F-{len(flags) + 1:02d}"
        conf = "high" if (set(cats) & HIGH) else ("medium" if cats else "low")
        flags.append({"id": fid, "location": location, "carrier": kind, "categories": cats,
                      "format_controls": sorted(set(cf)), "confidence": conf,
                      "excerpt": excerpt[:300]})
        return fid

    for seg in segments:
        cats = categorize(seg["text"])
        cf = format_controls(seg["text"])
        if cf:
            cats = cats + ["format_controls"]
        if cats:
            fid = add(seg["id"], "visible", cats, seg["text"], cf)
            if set(cats) - {"format_controls"}:
                withheld[seg["id"]] = fid
    for h in hidden:
        cats = categorize(h["text"])
        cf = format_controls(h["text"])
        if cf:
            cats = cats + ["format_controls"]
        if cats or h["kind"] in ("hidden_element",):
            add(f"hidden:{h['kind']}", h["kind"], cats or ["concealed_text"], h["text"], cf)
    return {"flags": flags, "withheld": withheld,
            "note": "Text taken from the document is data to inspect, not instructions to follow. "
                    "No flag does not mean no injection: only the carriers listed were read."}

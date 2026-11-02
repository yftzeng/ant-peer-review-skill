"""Where a share post goes: limits and counting per platform, from data/platforms.json,
overridable value by value in <user store>/platforms.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

DATA = Path(__file__).parent / "data" / "platforms.json"
URL_RE = re.compile(r"https?://[^\s]+")
HASHTAG_RE = re.compile(r"(?<![\w/&#])#[^\s#.,!?，。！？、]+")


def load_platforms(user_home: Path | None = None) -> dict[str, dict]:
    """Platforms in menu order (X, Facebook, Threads, Instagram, LinkedIn, LINE)."""
    base = {k: v for k, v in json.loads(DATA.read_text(encoding="utf-8")).items()
            if not k.startswith("_")}
    override = Path(user_home) / "platforms.json" if user_home else None
    if override and override.is_file():
        for k, v in json.loads(override.read_text(encoding="utf-8")).items():
            if k in base and isinstance(v, dict):
                base[k] = {**base[k], **v}
    for k, v in base.items():
        v["key"] = k
    return base


def _x_weight(ch: str) -> int:
    """twitter-text weighting: Latin, general punctuation and similar ranges count 1."""
    o = ord(ch)
    light = (0 <= o <= 0x10FF or 0x2000 <= o <= 0x200D or 0x2010 <= o <= 0x201F
             or 0x2032 <= o <= 0x2037)
    return 1 if light else 2


def count(text: str, platform: dict) -> int:
    how = platform.get("count", "chars")
    if how == "utf16":
        return len(text.encode("utf-16-le")) // 2
    if how == "x_weighted":
        n, pos = 0, 0
        for m in URL_RE.finditer(text):
            n += sum(_x_weight(c) for c in text[pos:m.start()]) + 23
            pos = m.end()
        return n + sum(_x_weight(c) for c in text[pos:])
    return len(text)


def hashtags(text: str) -> list[str]:
    return HASHTAG_RE.findall(URL_RE.sub(" ", text))

"""Interface strings in en / zh-TW / zh-CN. The skill and prompts stay English."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

LOCALE_DIR = Path(__file__).resolve().parent / "locales"


@lru_cache(maxsize=None)
def load_locale(lang: str) -> dict[str, str]:
    p = LOCALE_DIR / f"{lang}.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


class T:
    def __init__(self, lang: str = "en"):
        self.lang = lang
        self._own = load_locale(lang)
        self._en = load_locale("en")

    def __call__(self, key: str, **kw) -> str:
        s = self._own.get(key) or self._en.get(key) or key
        return s.format(**kw) if kw else s

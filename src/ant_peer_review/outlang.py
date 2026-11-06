"""The languages the delivered text is written in, and their regional usage.

English is written as in the US, Traditional Chinese as used in Taiwan, Simplified
Chinese as used in mainland China. Usage is checked, not only asked for: terms and
spellings with one clear regional equivalent are replaced; terms that also have a
legitimate local meaning are only flagged (weak); characters of the other script must
be fixed. Quotes, URLs and protected names (titles, authors) are never changed."""
from __future__ import annotations

import re
from pathlib import Path

from .platforms import URL_RE

OUTPUT_LANGS = ["en", "zh-TW", "zh-CN"]          # menu order
LABELS = {"en": "English (US)", "zh-TW": "繁體中文（台灣用語）", "zh-CN": "简体中文（中国大陆用语）"}
GUIDE = {
    "en": "American English as written in the United States: US spelling (color, organize, "
          "center, program, canceled), US vocabulary and punctuation",
    "zh-TW": "Traditional Chinese as used in Taiwan: Taiwan vocabulary (軟體, 網路, 影片, "
             "資訊, 預設, 伺服器, 專案, 使用者, 程式, 透過), full-width punctuation and 「」 "
             "quotation marks; never Simplified characters or mainland terms",
    "zh-CN": "Simplified Chinese as used in mainland China: mainland vocabulary (软件, 网络, "
             "视频, 信息, 默认, 服务器, 项目, 用户, 程序, 通过), full-width punctuation and "
             "“” quotation marks; never Traditional characters or Taiwan terms",
}

# Characters used only in one script (pairs: simplified, traditional).
_PAIRS = ("们們 这這 说說 时時 发發 为為 会會 对對 经經 过過 还還 进進 现現 实實 动動 开開 "
          "关關 门門 问問 间間 长長 东東 车車 书書 见見 话話 语語 读讀 写寫 认認 识識 让讓 "
          "应應 该該 网網 络絡 软軟 视視 频頻 数數 据據 质質 设設 计計 个個 国國 学學 样樣 "
          "业業 电電 与與 务務 级級 产產 无無 体體").split()
SIMPLIFIED_ONLY = "".join(p[0] for p in _PAIRS)
TRADITIONAL_ONLY = "".join(p[1] for p in _PAIRS)

# zh-TW: mainland term (in Traditional script) -> Taiwan term.
TW_SAFE = {
    "源代碼": "原始碼", "代碼": "程式碼", "程序員": "程式設計師", "軟件": "軟體", "硬件": "硬體",
    "視頻": "影片", "默認": "預設", "網絡": "網路", "服務器": "伺服器", "鼠標": "滑鼠",
    "打印": "列印", "博客": "部落格", "數據庫": "資料庫", "屏幕": "螢幕", "內存": "記憶體",
    "菜單": "選單", "文件夾": "資料夾", "芯片": "晶片", "操作系統": "作業系統",
    "互聯網": "網際網路", "數字化": "數位化", "智能": "智慧", "短信": "簡訊", "出租車": "計程車",
    "搜索": "搜尋", "鏈接": "連結", "模塊": "模組", "緩存": "快取", "異步": "非同步",
    "線程": "執行緒", "變量": "變數", "數組": "陣列", "字符串": "字串", "硬盤": "硬碟",
    "激活": "啟用", "電鏡": "電子顯微鏡", "復盤": "檢討",
}
TW_FLAG = {
    "項目": "專案", "質量": "品質", "信息": "資訊", "用戶": "使用者", "支持": "支援",
    "運行": "執行", "通過": "透過", "程序": "程式", "對象": "物件", "函數": "函式",
    "數據": "資料", "調用": "呼叫", "接口": "介面", "登錄": "登入",
}
# A flagged term that is right in this sense: 質量 is Taiwan's word for mass.
FLAG_UNLESS = {"質量": re.compile(r"[\d倍克噸頓]|公斤|道爾頓|核糖體|分子|原子|能量|密度|重量|物理|守恆")}
FLAG_WINDOW = 8
# zh-CN: Taiwan term (in Simplified script) -> mainland term.
CN_SAFE = {
    "程式设计师": "程序员", "程式码": "代码", "原始码": "源代码", "软体": "软件", "硬体": "硬件",
    "伺服器": "服务器", "滑鼠": "鼠标", "列印": "打印", "部落格": "博客", "资料库": "数据库",
    "萤幕": "屏幕", "记忆体": "内存", "晶片": "芯片", "作业系统": "操作系统",
    "网际网路": "互联网", "网路": "网络", "简讯": "短信", "计程车": "出租车", "搜寻": "搜索",
    "模组": "模块", "快取": "缓存", "非同步": "异步", "执行绪": "线程", "变数": "变量",
    "阵列": "数组", "字串": "字符串", "硬碟": "硬盘",
}
CN_FLAG = {
    "专案": "项目", "资讯": "信息", "使用者": "用户", "影片": "视频", "预设": "默认",
    "物件": "对象", "程式": "程序", "透过": "通过", "品质": "质量",
}
# en: British spelling -> US, as (stem, US stem, allowed endings).
_ANY = r"\w*"
_VERB = r"(?:e|es|ed|ing|ation|ations|er|ers)?"
US_SPELLING = [
    ("colour", "color", _ANY), ("favour", "favor", _ANY), ("behaviour", "behavior", _ANY),
    ("honour", "honor", _ANY), ("labour", "labor", _ANY), ("neighbour", "neighbor", _ANY),
    ("flavour", "flavor", _ANY), ("humour", "humor", _ANY), ("rumour", "rumor", _ANY),
    ("organis", "organiz", _VERB), ("realis", "realiz", _VERB), ("recognis", "recogniz", _VERB),
    ("prioritis", "prioritiz", _VERB), ("optimis", "optimiz", _VERB),
    ("minimis", "minimiz", _VERB), ("maximis", "maximiz", _VERB),
    ("summaris", "summariz", _VERB), ("customis", "customiz", _VERB),
    ("centre", "center", r"(?:s|d)?"), ("theatre", "theater", r"s?"),
    ("defence", "defense", r"s?"), ("licence", "license", r"s?"),
    ("catalogue", "catalog", r"s?"), ("programme", "program", r"s?"),
    ("travelled", "traveled", ""), ("travelling", "traveling", ""),
    ("cancelled", "canceled", ""), ("cancelling", "canceling", ""),
    ("modelled", "modeled", ""), ("modelling", "modeling", ""), ("grey", "gray", r"s?"),
    ("whilst", "while", ""),
]
_QUOTED = re.compile(r"「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"\n]*\"|《[^》]*》")
_HAN = re.compile(r"[㐀-䶿一-鿿]")
_WORD = re.compile(r"[A-Za-z]+")


def guide(lang: str) -> str:
    return GUIDE.get(lang, lang)


def parse(value: str | None, default: str) -> list[str]:
    """'zh-TW,en' -> ['en', 'zh-TW'] (menu order). Raises ValueError on an unknown one."""
    picked = [x.strip() for x in (value or "").split(",") if x.strip()]
    bad = [x for x in picked if x not in OUTPUT_LANGS]
    if bad:
        raise ValueError(f"--output-lang takes {', '.join(OUTPUT_LANGS)}; unknown: {', '.join(bad)}")
    return [x for x in OUTPUT_LANGS if x in picked] or [default]


def of(intake: dict, fallback: str = "en") -> list[str]:
    """The run's output languages; runs made before the question default to their lang."""
    return list(intake.get("output_langs") or [intake.get("lang") or fallback])


def file_name(name: str, lang: str, langs: list[str]) -> str:
    """reply-pragmatic.md, or reply-pragmatic.zh-TW.md when several languages are written."""
    if len(langs) <= 1:
        return name
    p = Path(name)
    return f"{p.stem}.{lang}{p.suffix}"


def detect(text: str) -> str:
    """en, zh-TW or zh-CN, from the script alone."""
    han = len(_HAN.findall(text))
    if han == 0 or han < len(_WORD.findall(text)):
        return "en"
    simp = sum(text.count(c) for c in SIMPLIFIED_ONLY)
    trad = sum(text.count(c) for c in TRADITIONAL_ONLY)
    return "zh-CN" if simp > trad else "zh-TW"


def _rules(lang: str):
    if lang == "zh-TW":
        return TW_SAFE, TW_FLAG, SIMPLIFIED_ONLY
    if lang == "zh-CN":
        return CN_SAFE, CN_FLAG, TRADITIONAL_ONLY
    return {}, {}, ""


def _us_rx(stem: str, ending: str) -> re.Pattern:
    return re.compile(rf"\b({stem})({ending})\b", re.I)


def _case(src: str, dst: str) -> str:
    return dst.upper() if src.isupper() and len(src) > 1 else \
        dst[0].upper() + dst[1:] if src[:1].isupper() else dst


def _shielded(text: str, protect=()) -> tuple[str, list[str]]:
    kept: list[str] = []

    def keep(m):
        kept.append(m.group(0))
        return f"\x01{len(kept) - 1}\x01"

    out = URL_RE.sub(keep, _QUOTED.sub(keep, text))
    for p in sorted((p for p in protect if p), key=len, reverse=True):
        if p in out:
            kept.append(p)
            out = out.replace(p, f"\x01{len(kept) - 1}\x01")
    return out, kept


def _restore(text: str, kept: list[str]) -> str:
    while "\x01" in text:
        new = re.sub("\x01(\\d+)\x01", lambda m: kept[int(m.group(1))], text)
        if new == text:
            break
        text = new
    return text


def fix(text: str, lang: str | None, protect=()) -> tuple[str, list[str]]:
    """Replace terms and spellings with one clear regional equivalent."""
    if not lang:
        return text, []
    out, kept = _shielded(text, protect)
    changes: list[str] = []
    safe, _, _ = _rules(lang)
    for src in sorted(safe, key=len, reverse=True):
        if src in out:
            out = out.replace(src, safe[src])
            changes.append(f"{src} → {safe[src]}")
    if lang == "en":
        for stem, us, ending in US_SPELLING:
            rx = _us_rx(stem, ending)
            for m in dict.fromkeys(x.group(0) for x in rx.finditer(out)):
                changes.append(f"{m} → {rx.sub(lambda x: _case(x.group(1), us) + x.group(2), m)}")
            out = rx.sub(lambda x: _case(x.group(1), us) + x.group(2), out)
    return _restore(out, kept), changes


def _right_sense(view: str, term: str, at: int) -> bool:
    """A flagged term used in the sense the output language spells it that way."""
    rx = FLAG_UNLESS.get(term)
    return bool(rx and rx.search(view[max(0, at - FLAG_WINDOW):at + len(term) + FLAG_WINDOW]))


def check(view: str, lang: str | None) -> list[dict]:
    """Issues in the scan view (quotes, URLs and protected names already removed)."""
    if not lang:
        return []
    out = []
    safe, flag, wrong = _rules(lang)
    script = "".join(dict.fromkeys(c for c in view if c in wrong))
    if script:
        out.append({"code": "script_mismatch", "level": "hard", "detail": script[:10]})
    for src in sorted(safe, key=len, reverse=True):
        if src in view:
            out.append({"code": "locale_term", "level": "strong", "detail": f"{src} → {safe[src]}"})
    for src, dst in flag.items():
        if any(not _right_sense(view, src, m.start()) for m in re.finditer(re.escape(src), view)):
            out.append({"code": "locale_term", "level": "weak", "detail": f"{src} → {dst}"})
    if lang == "en":
        for stem, us, ending in US_SPELLING:
            m = _us_rx(stem, ending).search(view)
            if m:
                out.append({"code": "us_spelling", "level": "strong",
                            "detail": f"{m.group(0).lower()} → {us}{m.group(2).lower()}"})
    return out

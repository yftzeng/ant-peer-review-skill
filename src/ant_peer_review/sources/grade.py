"""Source grades, shared with ant-pr-review: the checker names each source's kind, code
checks the host. An official kind on a host that is not official is only a claim (C);
one outlet is one source. A claim is strong with one A or two B from different outlets.

A source with no kind (a ledger from before grading) is ungraded and keeps the old rules.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

SOURCE_KINDS = ("law_database", "court", "regulator", "registry", "exchange_filing",
                "academic", "independent", "company_claim", "aggregator", "lead")
GRADE = {"law_database": "A", "court": "A", "regulator": "A", "registry": "A",
         "exchange_filing": "A", "academic": "A", "independent": "B",
         "company_claim": "C", "aggregator": "C", "lead": "C"}
OFFICIAL = re.compile(r"(?:^|\.)(?:gov|gov\.[a-z]{2}|go\.[a-z]{2}|gob\.[a-z]{2}|nat\.gov\.tw|"
                      r"europa\.eu|twse\.com\.tw|tpex\.org\.tw|sec\.gov|sse\.com\.cn|"
                      r"szse\.cn|hkex\.com\.hk)$")
SCHOLARLY = re.compile(r"(?:^|\.)(?:doi\.org|arxiv\.org)$")
_SUFFIX2 = {"co", "com", "org", "net", "gov", "edu", "ac", "or", "ne", "go", "idv", "gob"}


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".").removeprefix("www.")


def outlet(url: str) -> str:
    """The registrable name without its suffix: bbc.co.uk and bbc.com are one outlet."""
    parts = host(url).split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SUFFIX2:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


def grade_source(url: str, kind: str | None) -> str:
    """A, B or C; "" when the kind is missing or unknown."""
    g = GRADE.get(kind or "")
    if g != "A":
        return g or ""
    if kind == "academic":
        return "A" if SCHOLARLY.search(host(url)) else "B"  # a publisher's page: independent
    return "A" if OFFICIAL.search(host(url)) else "C"


def strength(sources: list[dict]) -> str:
    """strong, single, weak or ungraded; "" with no source."""
    if not sources:
        return ""
    best: dict[str, str] = {}
    for s in sources:
        g = s.get("grade") or ""
        o = outlet(s.get("url") or "")
        if g and (o not in best or g < best[o]):
            best[o] = g
    grades = list(best.values())
    if "A" in grades or grades.count("B") >= 2:
        return "strong"
    if "B" in grades:
        return "single"
    return "weak" if grades else "ungraded"


def is_evidence(claim: dict) -> bool:
    """May this claim outrank a reviewer's dispute? Not when only C sources back it."""
    return strength(claim.get("sources") or []) != "weak"

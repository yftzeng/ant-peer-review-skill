"""Feed articles across runs: order them, and find the ones an earlier run reviewed."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from .jsonio import read_json
from .workspace import Run, list_runs

TRACKING = ("utm_", "fbclid", "gclid", "mc_", "ref", "sc")  # sc: ithelp's "?sc=rss.iron"


def article_key(url: str) -> str:
    """The same article under different tracking parameters gets the same key."""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not any(k.lower() == t or (t.endswith("_") and k.lower().startswith(t))
                        for t in TRACKING)]
    return f"{(p.hostname or '').lower()}{p.path.rstrip('/')}" + \
        (f"?{urlencode(sorted(query))}" if query else "")


def parse_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def oldest_first(items: list[dict]) -> list[dict]:
    """Dated items oldest first; undated ones after them, in feed order."""
    dated = [(parse_date(it.get("date", "")), i, it) for i, it in enumerate(items)]
    return [it for d, _, it in sorted((x for x in dated if x[0]), key=lambda x: (x[0], x[1]))] \
        + [it for d, _, it in dated if not d]


def reviewed_articles(runs_dir: Path) -> dict[str, list[dict]]:
    """article key -> earlier runs of it, oldest first: {run, date, total, grade}."""
    from .report import latest_version
    out: dict[str, list[dict]] = {}
    for r in list_runs(runs_dir):
        intake = read_json(r.path("00-intake.json"), default={})
        v = latest_version(r)
        meta = read_json(r.path(f"06-report.v{v}.json"), default={}) if v else {}
        for tgt in intake.get("targets", []):
            if tgt.get("kind") == "feed_item":
                out.setdefault(article_key(tgt["value"]), []).append({
                    "run": r.id, "date": r.state().get("created_at", "")[:10],
                    "total": meta.get("total"), "grade": meta.get("grade")})
    return out


def latest_feed_run(runs_dir: Path) -> Run | None:
    for r in reversed(list_runs(runs_dir)):
        if feed_of(r):
            return r
    return None


def feed_of(run: Run) -> str:
    for tgt in read_json(run.path("00-intake.json"), default={}).get("targets", []):
        if tgt.get("feed"):
            return tgt["feed"]
    return ""

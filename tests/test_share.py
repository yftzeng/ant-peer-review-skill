import pytest

import ant_peer_review.cli as cli
from ant_peer_review.decision import run_decision
from ant_peer_review.jsonio import append_jsonl, read_json, write_json
from ant_peer_review.refresh import compute_consensus
from ant_peer_review.store import Config, Store
from ant_peer_review.ui import ScriptedIO
from ant_peer_review.voice import load_voice, save_voice
from ant_peer_review.workspace import list_runs
from helpers import ScriptBackend
from test_cli import CountingFake, NoAskIO, TEXT
from test_decision import M, TH, setup

URL = "https://ex.example/a"
SUMMARY = {"summary": "s", "key_points": []}


def voice(platform, **counts):
    return {"platform": platform, "posts": 3, "samples": [], "description": f"{platform} voice",
            "openers": [], "closers": [], "emoji": "", "hashtags": "", "median_units": 80,
            "hashtags_per_post": 0, "allow": [], "deny": [], "updated_at": "",
            "style_counts": {s: counts.get(s, 0) for s in
                             ("summary", "insight", "question", "addon", "pick")}}


def share_run(tmp_path, platforms, styles, flags=(), take=""):
    run, store = setup(tmp_path, flags_opus=flags)
    intake = read_json(run.path("00-intake.json"))
    intake["purpose"] = "share"
    intake["targets"] = [{"kind": "url", "value": URL + "?utm_source=rss&sc=rss.iron",
                          "title": "Title"}]
    intake["share"] = {"platforms": platforms, "stance": "recommend", "take": take,
                       "styles": styles}
    write_json(run.path("00-intake.json"), intake)
    return run, store


def posts(**texts):
    return {"posts": [{"key": k.replace("_", "-"), "text": v} for k, v in texts.items()]}


def decide(run, store, b, io=None):
    return run_decision(io, run, store, models=M, lang="en", thresholds=TH, min_repeats=3,
                        backend=b)


X_POST = f"Revenue grew 40% in 2025, says Title. Worth the read: {URL}"
IG_POST = "Title by its author: revenue grew 40% in 2025. Link in bio."


# @S-share-004
def test_share_run_writes_one_post_per_platform_and_style(tmp_path):
    run, store = share_run(tmp_path, ["x", "instagram"],
                           {"x": ["summary"], "instagram": ["summary", "insight"]})
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "share"): posts(x_summary=X_POST, instagram_summary=IG_POST,
                                             instagram_insight="Title reminded me how 2025 went. "
                                                               "Link in bio.")})
    decide(run, store, b)
    names = sorted(p.name for p in run.root.glob("share-*.md"))
    assert names == ["share-checks.md", "share-instagram-insight.md",
                     "share-instagram-summary.md", "share-x-summary.md"]
    assert [c["task"] for c in b.calls].count("share") == 1
    assert URL in run.path("share-x-summary.md").read_text()
    share_prompt = [c for c in b.calls if c["task"] == "share"][0]["prompt"]
    assert f'"url": "{URL}"' in share_prompt and "utm_source" not in share_prompt
    ig = run.path("share-instagram-summary.md").read_text()
    assert URL not in ig and "Title" in ig and not ig.startswith(">")
    assert not run.path("audit.md").exists()          # nothing to adopt in a share run
    assert read_json(run.path("08-decision.json"))["choice"] == "share"
    checks = run.path("share-checks.md").read_text()
    assert "share-x-summary.md" in checks and "✓" in checks
    assert "Fit to share" in run.path("review.md").read_text()


# @N-share-001
def test_invented_experience_is_never_passed_silently(tmp_path):
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "share"): posts(x_summary="我曾經導入過這套，40% 很真實 " + URL)})
    decide(run, store, b)
    text = run.path("share-x-summary.md").read_text()
    assert text.startswith("> ⚠") and "invented_experience" in text
    assert [c["task"] for c in b.calls].count("share_rewrite") == 2


# @S-share-005
def test_vetoed_article_not_recommended(tmp_path):
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]}, flags=["hallucination"])
    append_jsonl(run.path("factcheck/ledger.jsonl"), {
        "id": "C01", "anchor": "D1.P03.S1", "text": "Revenue grew 40% in 2025", "type": "number",
        "status": "unsupported", "reason": "", "sources": [], "refs": [], "checked_by": "sonnet"})
    assert compute_consensus(run, M, TH)["red_lines"]["hallucination"]["status"] == "confirmed"
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "share"): posts(x_summary=X_POST)})
    decide(run, store, b)
    text = run.path("share-x-summary.md").read_text()
    assert text.startswith("> ⛔") and "Serious factual error" in text
    assert "Not fit to share" in run.path("review.md").read_text()
    assert "Revenue grew 40% in 2025" in [c for c in b.calls if c["task"] == "share"][0]["prompt"]


# @S-share-003
def test_borrowed_voice(tmp_path):
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    save_voice(store.home, voice("threads", question=3))
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "share"): posts(x_summary=X_POST)})
    decide(run, store, b)
    prompt = [c for c in b.calls if c["task"] == "share"][0]["prompt"]
    assert "threads voice" in prompt and "borrowed from threads" in prompt
    assert "Threads" in run.path("share-checks.md").read_text()


@pytest.fixture
def env(tmp_path, monkeypatch):
    from test_cli import OfflineCrawler
    monkeypatch.setattr(cli, "get_backend", lambda name: CountingFake())
    monkeypatch.setattr(cli, "make_feed_crawler", lambda store: OfflineCrawler())
    store = Store(tmp_path / "home")
    store.save_config(Config())
    return store


# @S-share-002
def test_voice_learned_per_platform(env):
    io = ScriptedIO(["第一篇貼文，讀完很有感。", "---", "第二篇：三個重點。", "---",
                     "第三篇，你們怎麼看？", "/done", "扎實", "賦能"])
    assert cli.main(["voice", "linkedin"], io=io, store=env) == 0
    v = load_voice(env.home, "linkedin")
    assert v["posts"] == 3 and v["allow"] == ["扎實"] and v["deny"] == ["賦能"]
    assert v["description"] and sum(v["style_counts"].values()) == 3 and v["median_units"] > 0
    assert [t for _, t in CountingFake.calls].count("voice") == 1
    io = ScriptedIO([])
    cli.main(["voice", "list"], io=io, store=env)
    line = next(ln for ln in io.text.splitlines() if "LinkedIn" in ln)
    assert "3" in line
    assert any("X/Twitter" in ln and "—" in ln for ln in io.text.splitlines())


# @S-share-001
def test_share_intake_order_and_preselection(env):
    save_voice(env.home, voice("linkedin", insight=3, summary=1))
    io = ScriptedIO(["3", "Some pasted article text with 2025 numbers.", "/done",
                     "1", "",          # platforms: tick X as well, confirm
                     "",               # stance: recommend
                     "",               # own take: none
                     "", "",           # styles for X, LinkedIn: keep preselection
                     ""])              # fact sources
    cli.main([], io=io, store=env)
    text = io.text
    labels = ["X/Twitter", "Facebook", "Threads", "Instagram", "LinkedIn", "LINE"]
    first = text.index("X/Twitter")
    assert [text.index(lb, first) for lb in labels] == sorted(text.index(lb, first) for lb in labels)
    assert "[x] LinkedIn" in text
    intake = read_json(list_runs(env.runs_dir)[0].path("00-intake.json"))
    assert intake["purpose"] == "share"
    assert intake["share"] == {"platforms": ["x", "linkedin"], "stance": "recommend", "take": "",
                               "styles": {"x": ["summary"], "linkedin": ["insight"]}}
    assert "Audience card" not in text and "Brand name" not in text


# @S-share-006
def test_share_from_arguments(env):
    code = cli.main(["new", "--yes", "--backend", "fake", "--purpose", "share", "--target", TEXT,
                     "--platform", "x,linkedin", "--stance", "recommend", "--take", "我們也遇過"],
                    io=NoAskIO(), store=env)
    assert code == 3
    run = list_runs(env.runs_dir)[-1]
    assert cli.main(["decide", run.id, "--yes"], io=NoAskIO(), store=env) == 0
    assert run.path("share-x-summary.md").exists() and run.path("share-linkedin-insight.md").exists()
    io = NoAskIO()
    assert cli.main(["new", "--yes", "--purpose", "share", "--target", TEXT, "--platform", "myspace"],
                    io=io, store=env) == cli.EXIT_USAGE
    assert "linkedin" in io.text
    io = NoAskIO()
    assert cli.main(["new", "--yes", "--purpose", "share", "--target", TEXT, "--platform", "x",
                     "--stance", "love"], io=io, store=env) == cli.EXIT_USAGE
    assert "reserved" in io.text

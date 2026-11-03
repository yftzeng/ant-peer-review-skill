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
    CountingFake.calls = []
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
                     "", "",           # output languages, angle: comment
                     "1", "4", "",     # platforms: untick Facebook, tick X as well, confirm
                     "2",              # X has no voice: borrow LinkedIn's
                     "",               # stance: recommend
                     "",               # own take: none
                     "", "",           # styles for X, LinkedIn: keep preselection
                     ""])              # fact sources
    cli.main([], io=io, store=env)
    text = io.text
    labels = ["Facebook", "Threads", "Instagram", "X/Twitter", "LinkedIn", "LINE"]
    first = text.index("Facebook")
    assert [text.index(lb, first) for lb in labels] == sorted(text.index(lb, first) for lb in labels)
    assert "[x] Facebook" in text and "[x] LinkedIn" in text
    assert "X/Twitter has no voice of yours" in text and "LinkedIn has no voice" not in text
    assert "LinkedIn: your voice is applied (3 posts" in text
    intake = read_json(list_runs(env.runs_dir)[0].path("00-intake.json"))
    assert intake["purpose"] == "share"
    assert intake["share"] == {"platforms": ["x", "linkedin"], "angle": "comment",
                               "stance": "recommend", "take": "",
                               "styles": {"x": ["summary"], "linkedin": ["insight"]},
                               "voices": {"x": "borrow", "linkedin": "own"}}
    assert "Audience card" not in text and "Brand name" not in text


# @S-share-007
def test_voice_created_inside_the_intake(env):
    answers = ["3", "Some pasted article text with 2025 numbers.", "/done", "", "",
               "1 2", "",                                    # platforms: Threads only
               "1",                                          # create its voice now
               "一篇。", "---", "兩篇。", "---", "三篇。", "/done", "扎實", "賦能",
               "", "",                                       # stance, own take
               "", ""]                                       # Threads styles, fact sources
    io = ScriptedIO(answers)
    cli.main([], io=io, store=env)
    v = load_voice(env.home, "threads")
    assert v["posts"] == 3 and v["allow"] == ["扎實"] and v["deny"] == ["賦能"]
    intake = read_json(list_runs(env.runs_dir)[-1].path("00-intake.json"))
    assert intake["share"]["styles"]["threads"] == ["insight"]      # the fake voice's top style
    assert intake["share"]["voices"] == {"threads": "own"}
    assert [t for _, t in CountingFake.calls].count("voice") == 1

    io = ScriptedIO(["3", "Another article, 2026.", "/done", "", "", "1", "", "", "",  # Threads ticked now; Facebook off
                     "6", "",                                # tick "rebuild this voice"
                     "新的一篇。", "/done", "", "",
                     "", ""])                                # styles again, fact sources
    cli.main([], io=io, store=env)
    assert "rebuild" in io.text.lower()
    assert load_voice(env.home, "threads")["posts"] == 1


# @S-share-008
def test_neutral_never_ask_is_remembered(env, tmp_path):
    save_voice(env.home, voice("threads", question=3))
    io = ScriptedIO(["3", "Article text, 2025.", "/done", "", "", "1 2 4", "",  # X only (Facebook, Threads were ticked)
                     "4", "", "", "", ""])                          # never ask; stance, take, style, facts
    cli.main([], io=io, store=env)
    run = list_runs(env.runs_dir)[-1]
    assert read_json(run.path("00-intake.json"))["share"]["voices"] == {"x": "neutral"}
    io = ScriptedIO(["3", "Article text, 2026.", "/done", "", "", "1 2 4", "", "", "", "", ""])
    cli.main([], io=io, store=env)
    assert "X/Twitter has no voice of yours" not in io.text and "Post styles for X" in io.text

    run2, store2 = share_run(tmp_path / "w", ["x"], {"x": ["summary"]})
    save_voice(store2.home, voice("threads", question=3))
    intake = read_json(run2.path("00-intake.json"))
    intake["share"]["voices"] = {"x": "neutral"}
    write_json(run2.path("00-intake.json"), intake)
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "share"): posts(x_summary=X_POST)})
    decide(run2, store2, b)
    prompt = [c for c in b.calls if c["task"] == "share"][0]["prompt"]
    assert "threads voice" not in prompt and "no voice file" in prompt


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


# @S-share-009
def test_share_neither_weighs_nor_scores(tmp_path):
    from ant_peer_review.pipeline import Ctx, ph_rubric
    from ant_peer_review.rubric import propose
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    ctx = Ctx(io=NoAskIO(), store=store, cfg=Config(), backend=None, models=M, lang="en",
              interactive=True, options={"weights": {"macro": 70, "accuracy": 10, "micro": 10,
                                                     "impact": 10}})
    ph_rubric(run, ctx)                                   # NoAskIO fails on any question
    intake = read_json(run.path("00-intake.json"))
    assert read_json(run.path("02-rubric.json")) == propose(intake["audience"])

    append_jsonl(run.path("factcheck/ledger.jsonl"), {
        "id": "C01", "anchor": "D1.P03.S1", "text": "Revenue grew 40% in 2025", "type": "number",
        "status": "unsupported", "reason": "", "sources": [], "refs": [], "checked_by": "sonnet"})
    cons = compute_consensus(run, M, TH)
    assert not any(v["status"] == "confirmed" for v in cons["red_lines"].values())
    from ant_peer_review.report import write_report
    write_report(run, cons, lang="en")                    # as the report phase would
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "share"): posts(x_summary=X_POST)})
    decide(run, store, b)
    review = run.path("review.md").read_text()
    assert "Fit to share, leaving out: Revenue grew 40% in 2025" in review
    for gone in ("Total", "Grade", "| Structure |"):        # no score row per dimension
        assert gone not in review, gone
    from ant_peer_review.report import latest_version
    report = run.path(f"06-report.v{latest_version(run)}.md").read_text()
    assert "Total" not in report and "Grade" not in report
    prompt = [c for c in b.calls if c["task"] == "share"][0]["prompt"]
    assert '"total"' not in prompt and '"grade"' not in prompt and '"scores"' not in prompt


# @S-share-010
def test_share_intake_asks_angle_and_distill_rules(env):
    io = ScriptedIO(["3", "Some pasted article text with 2025 numbers.", "/done",
                     "",               # output language
                     "2",              # angle: distill
                     "1", "2", "",     # platforms: Facebook (ticked) off, Threads on
                     "",               # Threads has no voice: neutral
                     "",               # own take: none
                     "",               # Threads styles: keep insight
                     "",               # source line: no (the default)
                     ""])              # fact sources
    cli.main([], io=io, store=env)
    text = io.text
    assert "Comment" in text and "Distill" in text
    assert text.index("Distill") < text.index("Facebook")
    assert "stance" not in text.lower()
    styles = text[text.index("Post styles for Threads"):]
    styles = styles[:styles.index("›")]
    from ant_peer_review.i18n import T
    t = T("en")
    assert f"[x] {t('share.style.insight')}" in styles and t("share.style.question") in styles
    assert t("share.style.summary") not in styles and t("share.style.pick") not in styles
    intake = read_json(list_runs(env.runs_dir)[-1].path("00-intake.json"))
    assert intake["share"]["angle"] == "distill" and intake["share"]["credit"] is False
    assert "1) [x] Facebook" in text and "2) [ ] Threads" in text
    assert "recommended" not in t("share.credit.yes").lower()
    assert "stance" not in intake["share"] and intake["share"]["styles"] == {"threads": ["insight"]}


def distill_run(tmp_path, credit=True, flags=()):
    run, store = share_run(tmp_path, ["x", "instagram"], {"x": ["insight"], "instagram": ["insight"]},
                           flags=flags)
    intake = read_json(run.path("00-intake.json"))
    intake["share"].update(angle="distill", credit=credit)
    intake["share"].pop("stance", None)
    intake["output_langs"] = ["zh-TW"]
    intake["analysis"] = {"targets": [{"title": "Title", "author": "Jane Roe",
                                       "organization": "Example News"}]}
    write_json(run.path("00-intake.json"), intake)
    return run, store


X_LEAK = "Acme 的經驗說明，流程越短，錯誤越少。你的團隊會先砍哪一步？"
X_OK = "流程越短，錯誤越少。每多一次交接，就多一個出錯的地方。你會先砍哪一步？"
IG_LEAK = "Jane Roe 提醒我，流程越短越好。"
IG_OK = "流程越短，出錯的地方越少。交接本身就是風險。"


ANALYSIS = {"purpose": "推一個新工具，用誇大的功能搶關注",
            "claims": [{"claim": "原本幾天，現在 3 分鐘內搞定", "status": "unsupported", "action": "keep",
                        "correction": ""},
                       {"claim": "純 Rust 打造", "status": "supported", "action": "keep", "correction": ""}],
            "direction": "middle", "why": "方法有價值，宣傳造假",
            "thesis": "轉傳文說得比原始文件多的部分，預設是行銷。",
            "anchors": ["主打功能在專案文件裡找不到"], "names": ["Acme"]}


# @S-share-011
# @S-share-012
def test_distilled_post_names_no_one_and_ends_with_source(tmp_path):
    run, store = distill_run(tmp_path)
    first = posts(x_insight=X_LEAK, instagram_insight=IG_LEAK)
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "share_analysis"): ANALYSIS, ("*", "share"): first,
                       ("*", "share_rewrite"): posts(x_insight=X_OK, instagram_insight=IG_OK)})
    decide(run, store, b)
    share_sys = [c for c in b.calls if c["task"] == "share"][0]["system"]
    assert "Write from the analysis" in share_sys and "names" in share_sys
    ask = [c for c in b.calls if c["task"] == "share_rewrite"][0]["prompt"]
    assert "name_leak: Acme" in ask and "name_leak: Jane Roe" in ask
    x = run.path("share-x-insight.md").read_text().strip()
    assert x.startswith("流程越短") and x.endswith("延伸自：Title https://ex.example/a")
    ig = run.path("share-instagram-insight.md").read_text().strip()
    assert ig.endswith("延伸自：Title") and "https://" not in ig
    checks = run.path("share-checks.md").read_text()
    assert "no_concrete_detail" not in checks and "no_attribution" not in checks
    judge = [c for c in b.calls if c["task"] == "judge"][0]
    for check in ("platitude", "paraphrase", "ignores_review", "direction"):
        assert check in judge["system"], check
    assert ANALYSIS["thesis"] in judge["prompt"]               # judged against the analysis


def test_distill_without_credit_adds_no_source_line(tmp_path):
    run, store = distill_run(tmp_path, credit=False)
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "share_analysis"): ANALYSIS,
                       ("*", "share"): posts(x_insight=X_OK, instagram_insight=IG_OK)})
    decide(run, store, b)
    assert run.path("share-x-insight.md").read_text().strip() == X_OK


# @S-share-012
def test_judge_extra_checks_need_quoted_evidence():
    from ant_peer_review.gate import DISTILL_CHECKS, STRONG, judge
    b = ScriptBackend({("*", "judge"): {"verdicts": [{"key": "k", "checks": [
        {"name": "platitude", "pass": False, "evidence": "流程越短"},
        {"name": "paraphrase", "pass": False, "evidence": "not in the text"}]}]}})
    out = judge(b, "opus", {"k": "流程越短，錯誤越少。"}, extra=DISTILL_CHECKS, context="ANALYSIS")
    assert out == {"k": [{"code": "judge:platitude", "level": STRONG, "detail": "流程越短"}]}
    assert "ignores_review" in b.calls[0]["system"] and "ANALYSIS" in b.calls[0]["prompt"]


# @S-share-013
def test_angle_from_arguments(env):
    cli.main(["new", "--yes", "--backend", "fake", "--purpose", "share", "--target", TEXT,
              "--platform", "x", "--angle", "distill"], io=NoAskIO(), store=env)
    share = read_json(list_runs(env.runs_dir)[-1].path("00-intake.json"))["share"]
    assert share["angle"] == "distill" and share["credit"] is False
    for flag, want in (("--credit", True), ("--no-credit", False)):
        cli.main(["new", "--yes", "--backend", "fake", "--purpose", "share", "--target", TEXT,
                  "--platform", "x", "--angle", "distill", flag], io=NoAskIO(), store=env)
        assert read_json(list_runs(env.runs_dir)[-1].path("00-intake.json"))["share"]["credit"] is want
    cli.main(["new", "--yes", "--backend", "fake", "--purpose", "share", "--target", TEXT],
             io=NoAskIO(), store=env)
    assert read_json(list_runs(env.runs_dir)[-1].path("00-intake.json"))["share"]["platforms"] == ["facebook"]
    assert share["styles"] == {"x": ["insight"]} and "stance" not in share
    cli.main(["new", "--yes", "--backend", "fake", "--purpose", "share", "--target", TEXT,
              "--platform", "x"], io=NoAskIO(), store=env)
    assert read_json(list_runs(env.runs_dir)[-1].path("00-intake.json"))["share"]["angle"] == "comment"
    io = NoAskIO()
    assert cli.main(["new", "--yes", "--purpose", "share", "--target", TEXT, "--platform", "x",
                     "--angle", "rant"], io=io, store=env) == cli.EXIT_USAGE
    assert "distill" in io.text


def ledger(run, *rows):
    for i, (text, status) in enumerate(rows, 1):
        append_jsonl(run.path("factcheck/ledger.jsonl"), {
            "id": f"C{i:02d}", "anchor": "D1.P03.S1", "text": text, "type": "number", "status": status,
            "reason": f"reason {i}", "sources": [], "refs": [], "checked_by": "sonnet"})


# @S-share-014
def test_distill_starts_with_an_analysis(tmp_path):
    run, store = distill_run(tmp_path, flags=["hallucination"])
    ledger(run, ("原本幾天，現在 3 分鐘內搞定", "unsupported"), ("純 Rust 打造", "supported"))
    assert compute_consensus(run, M, TH)["red_lines"]["hallucination"]["status"] == "confirmed"
    leak = "轉傳文說得比原始文件多的部分，預設是行銷。號稱 3 分鐘完成的那種。"
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "share_analysis"): ANALYSIS,
                       ("*", "share"): posts(x_insight=leak, instagram_insight=IG_OK),
                       ("*", "share_rewrite"): posts(x_insight=X_OK)})
    decide(run, store, b)
    tasks = [c["task"] for c in b.calls]
    assert tasks.count("share_analysis") == 1 and tasks.index("share_analysis") < tasks.index("share")
    ap = b.calls[tasks.index("share_analysis")]["prompt"]
    for want in ("原本幾天，現在 3 分鐘內搞定", "unsupported", "reason 1", "oppose or middle",
                 "Revenue grew 40% in 2025"):
        assert want in ap, want
    sp = b.calls[tasks.index("share")]["prompt"]
    assert ANALYSIS["thesis"] in sp and "First para." not in sp        # the analysis, not the article
    md = run.path("share-analysis.md").read_text()
    assert "原本幾天，現在 3 分鐘內搞定" in md and "drop" in md and ANALYSIS["thesis"] in md
    ask = b.calls[tasks.index("share_rewrite")]["prompt"]
    assert "dropped_claim: 3" in ask


# @S-share-014
def test_analysis_rows_cite_claim_ids_and_merge_near_duplicates(tmp_path):
    run, store = distill_run(tmp_path, flags=["hallucination"])
    ledger(run, ("原本需要幾天的人工逆向分析，現在幾分鐘內搞定", "unsupported"), ("純 Rust 打造", "supported"),
           ("記憶體佔用極低", "unsupported"), ("原本需要幾天的人工逆向分析，現在幾分鐘內完成", "unsupported"),
           ("記憶體占用極低", "unsupported"), ("內建符號執行引擎", "unsupported"))
    analysis = dict(ANALYSIS, claims=[
        {"ids": ["C01", "C04"], "claim": "幾天變幾分鐘", "status": "無依據（行銷）", "action": "drop", "correction": ""},
        {"ids": [], "claim": "純 Rust 打造，記憶體很低", "status": "部分成立", "action": "qualify", "correction": ""},
        {"ids": ["C02"], "claim": "純 Rust", "status": "成立", "action": "keep", "correction": ""}])
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "share_analysis"): analysis,
                       ("*", "share"): posts(x_insight=X_OK, instagram_insight=IG_OK)})
    decide(run, store, b)
    ap = next(c for c in b.calls if c["task"] == "share_analysis")["prompt"]
    assert '"id": "C03"' in ap
    rows = read_json(run.path("share-analysis.json"))["claims"]
    assert [r["status"] for r in rows] == ["unsupported", "unchecked", "supported", "unsupported", "unsupported"]
    assert rows[0]["ids"] == ["C01", "C04"] and rows[3]["ids"] == ["C03", "C05"] and rows[4]["ids"] == ["C06"]
    assert all(r["action"] == "drop" for r in rows[3:])


# @S-share-015
def test_first_target_is_the_article_rest_are_references(tmp_path):
    from ant_peer_review.jsonio import write_text_atomic
    run, store = distill_run(tmp_path)
    write_text_atomic(run.path("01-sources/normalized/D2.md"), "README SELF DESCRIPTION of the project.\n")
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "share_analysis"): ANALYSIS,
                       ("*", "share"): posts(x_insight=X_OK, instagram_insight=IG_OK)})
    decide(run, store, b)
    ap = next(c for c in b.calls if c["task"] == "share_analysis")["prompt"]
    art, refs = ap.index("Article excerpt"), ap.index("References")
    assert art < ap.index("First para.") < refs < ap.index("README SELF DESCRIPTION")
    assert "own description" in ap[refs:ap.index("README SELF DESCRIPTION")]


# @S-share-016
def test_correcting_distill_post_is_not_marked_not_recommended(tmp_path):
    from ant_peer_review.i18n import T
    run, store = distill_run(tmp_path, flags=["hallucination"])
    ledger(run, ("Revenue grew 40% in 2025", "unsupported"))
    assert compute_consensus(run, M, TH)["red_lines"]["hallucination"]["status"] == "confirmed"
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "share_analysis"): ANALYSIS,
                       ("*", "share"): posts(x_insight=X_OK, instagram_insight=IG_OK)})
    decide(run, store, b)
    text = run.path("share-x-insight.md").read_text()
    head = T("en")("share.corrects", lines="x").split("(")[0]
    assert text.startswith("> ⚠ " + head) and "Not recommended" not in text.split("\n")[0]

import ant_peer_review.cli as cli
from ant_peer_review.gate import HARD, STRONG, WEAK, autofix, rule_check
from ant_peer_review.i18n import T
from ant_peer_review.jsonio import read_json, write_json, write_text_atomic
from ant_peer_review.ui import ScriptedIO
from ant_peer_review.workspace import list_runs
from helpers import ScriptBackend
from test_analysis import page_env  # noqa: F401  (fixture)
from test_cli import NoAskIO, TEXT
from test_decision import M, TH, setup
from test_deliver import SUMMARY, decide
from test_share import posts, share_run

URL = "https://ex.example/a"


def codes(issues):
    return {(i["code"], i["level"], i["detail"]) for i in issues}


# @S-output-language-001
def test_interactive_intake_asks_output_languages(page_env):  # noqa: F811
    store, base = page_env
    io = ScriptedIO(["1", base + "/page", "/done", "", "", "", ""])  # langs, card, facts, brand
    cli.main(["new", "--lang", "zh-TW"], io=io, store=store)
    text = io.text
    i = text.index("English (US)")
    assert text.index("繁體中文（台灣用語）") > i and text.index("简体中文（中国大陆用语）") > i
    assert "[x] 繁體中文（台灣用語）" in text and "[ ] English (US)" in text
    assert T("zh-TW")("outlang.source", lang="English (US)") in text
    assert text.index("English (US)") > text.index("Rates rise again")   # after the content check
    intake = read_json(list_runs(store.runs_dir)[0].path("00-intake.json"))
    assert intake["output_langs"] == ["zh-TW"]


def test_interactive_intake_ticks_several_in_menu_order(page_env):  # noqa: F811
    store, base = page_env
    io = ScriptedIO(["1", base + "/page", "/done", "3 1", "", "", "", ""])
    cli.main(["new", "--lang", "zh-TW"], io=io, store=store)
    intake = read_json(list_runs(store.runs_dir)[0].path("00-intake.json"))
    assert intake["output_langs"] == ["en", "zh-TW", "zh-CN"]


# @S-output-language-002
def test_output_languages_from_arguments(store):
    cli.main(["new", "--yes", "--backend", "fake", "--target", TEXT, "--lang", "en",
              "--output-lang", "zh-TW,en"], io=NoAskIO(), store=store)
    assert read_json(list_runs(store.runs_dir)[-1].path("00-intake.json"))["output_langs"] == \
        ["en", "zh-TW"]
    cli.main(["new", "--yes", "--backend", "fake", "--target", TEXT, "--lang", "en"],
             io=NoAskIO(), store=store)
    assert read_json(list_runs(store.runs_dir)[-1].path("00-intake.json"))["output_langs"] == ["en"]
    io = NoAskIO()
    assert cli.main(["new", "--yes", "--target", TEXT, "--output-lang", "fr"], io=io,
                    store=store) == cli.EXIT_USAGE
    assert "zh-TW" in io.text and "zh-CN" in io.text


# @S-output-language-003
# @N-output-language-001
def test_taiwan_usage():
    text = "這個軟件的視頻很好。這個項目我们會做。他說「軟件」，見 https://ex.example/軟件"
    fixed, changes = autofix(text, lang="zh-TW", protect=["視頻大全"])
    assert "這個軟體的影片很好" in fixed
    assert "軟件 → 軟體" in changes and "視頻 → 影片" in changes
    assert "「軟件」" in fixed and "https://ex.example/軟件" in fixed
    found = codes(rule_check(fixed, lang="zh-TW"))
    assert ("locale_term", WEAK, "項目 → 專案") in found
    assert ("script_mismatch", HARD, "们") in found
    assert not any(c == "locale_term" and "軟件" in d for c, _, d in found)
    title_kept, _ = autofix("推薦《視頻大全》這本書", lang="zh-TW", protect=["視頻大全"])
    assert "視頻大全" in title_kept
    assert ("locale_term", STRONG, "軟件 → 軟體") in codes(rule_check("這個軟件", lang="zh-TW"))
    assert not rule_check("這個軟體", lang="zh-TW")
    for mass in ("穹窿體的質量約為核糖體的三倍。", "總共約 9.5 兆道爾頓的質量。"):
        assert not any(c == "locale_term" for c, _, _ in codes(rule_check(mass, lang="zh-TW"))), mass
    assert ("locale_term", WEAK, "質量 → 品質") in codes(rule_check("這家店的質量很好。", lang="zh-TW"))
    far = "這家店的質量很好，服務也不錯，價格只有一半，回購率高了三倍。"   # a number far away is no mass
    assert ("locale_term", WEAK, "質量 → 品質") in codes(rule_check(far, lang="zh-TW"))


# @S-output-language-004
def test_mainland_usage_and_us_spelling():
    fixed, _ = autofix("这个软体很好。", lang="zh-CN")
    assert "这个软件" in fixed
    assert ("script_mismatch", HARD, "們") in codes(rule_check("我們的软件", lang="zh-CN"))
    en, changes = autofix('The colour of organised centres. He wrote "colour".', lang="en")
    assert en.startswith("The color of organized centers.") and '"colour"' in en
    assert any("colour → color" in c for c in changes)
    assert autofix("An organism and its organs.", lang="en")[0] == "An organism and its organs."
    assert ("us_spelling", STRONG, "colour → color") in codes(rule_check("a colour", lang="en"))


def _set_langs(run, langs):
    intake = read_json(run.path("00-intake.json"))
    intake["output_langs"] = langs
    write_json(run.path("00-intake.json"), intake)


# @S-output-language-005
def test_replies_written_once_per_output_language(tmp_path):
    from test_deliver import with_issue
    run, store = with_issue(tmp_path)
    _set_langs(run, ["zh-TW", "en"])

    def reply(prompt):
        return {"replies": [{"style": "pragmatic", "text": "結尾沒有回到開頭的論點，建議補一句。"}]}

    def reply_en(prompt):
        return {"replies": [{"style": "pragmatic", "text": "The ending does not return to the claim."}]}

    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []}})
    b.handlers[("*", "reply")] = lambda p: reply(p)
    calls = []

    def route(prompt):
        sys = b.calls[-1]["system"]
        calls.append(sys)
        return reply(prompt) if "Taiwan" in sys else reply_en(prompt)

    b.handlers[("*", "reply")] = route
    decide(run, store, None, choice="A", backend=b, reply_styles=["pragmatic"])
    assert run.path("reply-pragmatic.zh-TW.md").read_text().startswith("結尾")
    assert run.path("reply-pragmatic.en.md").read_text().startswith("The ending")
    assert not run.path("reply-pragmatic.md").exists()
    assert len(calls) == 2 and any("United States" in s for s in calls)
    checks = run.path("reply-checks.md").read_text()
    assert "reply-pragmatic.zh-TW.md" in checks and "reply-pragmatic.en.md" in checks


def test_share_posts_written_once_per_output_language(tmp_path):
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    _set_langs(run, ["zh-TW", "en"])
    zh = f"Title 提到 2025 年營收成長 40%，值得一讀：{URL}"
    en = f"Revenue grew 40% in 2025, says Title. Worth the read: {URL}"
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []}})
    b.handlers[("*", "share")] = lambda p: posts(x_summary=zh if "Taiwan" in b.calls[-1]["system"]
                                                 else en)
    from test_share import decide as share_decide
    share_decide(run, store, b)
    assert run.path("share-x-summary.zh-TW.md").read_text().startswith("Title 提到")
    assert run.path("share-x-summary.en.md").read_text().startswith("Revenue")
    assert [c["task"] for c in b.calls].count("share") == 2


# @S-output-language-006
def test_adopted_text_in_each_output_language(tmp_path):
    run, store = setup(tmp_path)
    write_text_atomic(run.path("07-revision/A.md"), "# 標題\n\n這個軟件在 2025 年營收成長 40%。\n")
    _set_langs(run, ["zh-TW", "en"])
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
                       ("*", "localize"): {"text": "# Title\n\nThe software's revenue grew 40% in 2025."}})
    decide(run, store, None, choice="A", backend=b, reply_styles=[])
    assert "這個軟件" in run.path("07-revision/adopted.md").read_text()
    assert "這個軟體在 2025 年" in run.path("audit.zh-TW.md").read_text()
    assert run.path("audit.en.md").read_text().startswith("# Title")
    assert not run.path("audit.md").exists()
    loc = [c for c in b.calls if c["task"] == "localize"]
    assert len(loc) == 1 and "United States" in loc[0]["system"]
    checks = run.path("final-checks.md").read_text()
    assert "audit.zh-TW.md" in checks and "audit.en.md" in checks and "軟件 → 軟體" in checks


def test_single_output_language_fixes_usage_without_a_model_call(tmp_path):
    run, store = setup(tmp_path)
    write_text_atomic(run.path("07-revision/A.md"), "# 標題\n\n這個軟件在 2025 年營收成長 40%。\n")
    _set_langs(run, ["zh-TW"])
    b = ScriptBackend({("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []}})
    decide(run, store, None, choice="A", backend=b, reply_styles=[])
    assert "這個軟體在 2025 年" in run.path("audit.md").read_text()
    assert not [c for c in b.calls if c["task"] == "localize"]


# @S-output-language-007
def test_draft_written_in_first_output_language(store):
    from ant_peer_review.pipeline import Ctx, ensure_draft
    from ant_peer_review.workspace import create_run
    run = create_run(store.runs_dir, "d", models=M, backend="script", lang="en")
    write_json(run.path("00-intake.json"), {"purpose": "drafting", "lang": "en",
                                            "output_langs": ["zh-TW"],
                                            "targets": [{"kind": "text", "value": "notes"}],
                                            "audience": {}})
    write_json(run.path("01-sources/segments.json"), {"D1": []})
    write_json(run.path("02-rubric.json"), {"dimensions": []})
    b = ScriptBackend({("*", "draft"): {"title": "標題", "paragraphs": ["內文。"]}})
    from ant_peer_review.store import Config
    ctx = Ctx(io=NoAskIO(), store=store, cfg=Config(), backend=b, models=M, lang="en",
              interactive=False)
    ensure_draft(run, ctx)
    assert "Traditional Chinese as used in Taiwan" in b.calls[0]["system"]

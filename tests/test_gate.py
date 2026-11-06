import json

from ant_peer_review.gate import (EDIT_RULES, JUDGE_SYSTEM, autofix, checks_md, judge, judge_model, needs_edit,
                                  rule_check, run_gate, verify_facts)
from ant_peer_review.i18n import T
from ant_peer_review.platforms import count, load_platforms
from helpers import ScriptBackend

t = T("zh-TW")


def codes(issues, level=None):
    return [i["code"] for i in issues if level is None or i["level"] == level]


# @S-writing-gate-001
def test_stock_phrases_with_allow_and_deny():
    text = "在這個快速變遷的時代，值得一提的是這篇文章。"
    strong = [i for i in rule_check(text) if i["level"] == "strong"]
    assert sorted(codes(strong)) == ["stock_phrase", "stock_phrase"]
    assert any("在這個快速變遷的時代" in i["detail"] for i in strong)
    strong = [i for i in rule_check(text, allow=["值得一提的是"]) if i["level"] == "strong"]
    assert len(strong) == 1 and "快速變遷" in strong[0]["detail"]
    assert codes(rule_check("這篇寫得很扎實。", deny=["扎實"]), "strong") == ["stock_phrase"]
    assert codes(rule_check("We delve into the data.")) == ["stock_phrase"]


# @S-writing-gate-002
def test_structural_tells_are_soft():
    text = "流程要先理順。真的就是這樣。\n🚀 一\n✅ 二\n🔥 三"
    issues = rule_check(text)
    assert codes(issues, "hard") == [] and codes(issues, "strong") == []
    assert "emoji_bullets" in codes(issues, "weak")
    for dash in ("——", "—", "–", "―"):
        assert "dashes" in codes(rule_check(f"先看結果{dash}再談方法。"), "hard"), dash
    assert "dashes" not in codes(rule_check("他說「先看——再談」。"))
    para = "這段話有二十個字左右，長度都很接近彼此差不多。"
    issues = rule_check("\n\n".join([para] * 4))
    assert codes(issues, "hard") == [] and "uniform_paragraphs" in codes(issues, "weak")
    assert "uniform_paragraphs" not in codes(rule_check("\n\n".join([para] * 4 + [para * 3])))


# @S-writing-gate-003
def test_invented_experience():
    text = "我曾經在團隊裡導入過 K8s，體會很深。"
    assert codes(rule_check(text), "hard") == ["invented_experience"]
    assert codes(rule_check(text, take="我們去年把服務搬上 K8s"), "hard") == []


# @S-writing-gate-004
def test_platform_counting_and_override(tmp_path):
    p = load_platforms()
    assert list(p) == ["x", "facebook", "threads", "instagram", "linkedin", "line"]
    text = "字" * 150 + " https://example.com/a/very/long/path?x=1"
    assert count(text, p["x"]) == 324
    assert "too_long" in codes(rule_check(text, platform=p["x"]), "hard")
    caption = "好文 " + " ".join(f"#t{i}" for i in range(6))
    assert "too_many_hashtags" in codes(rule_check(caption, platform=p["instagram"]), "hard")
    assert count("😀", p["line"]) == 2                      # UTF-16 units
    (tmp_path / "platforms.json").write_text(json.dumps({"x": {"max_units": 25000}}))
    p2 = load_platforms(tmp_path)
    assert p2["x"]["max_units"] == 25000 and p2["x"]["count"] == "x_weighted"
    assert "too_long" not in codes(rule_check(text, platform=p2["x"]), "hard")


# @S-writing-gate-005
# @N-writing-gate-001
def test_rewrite_twice_then_mark():
    calls = []

    def rewrite(failed):
        calls.append(failed)
        return {k: "在這個快速變遷的時代，還是這樣。" for k in failed}

    out = run_gate({"a": "在這個快速變遷的時代，這樣。", "b": "這篇寫得很清楚。"}, rewrite,
                   check=lambda k, text: rule_check(text))
    assert len(calls) == 2 and all(list(c) == ["a"] for c in calls)
    assert "stock_phrase" in calls[0]["a"]["reasons"][0]
    assert calls[0]["a"]["text"] == "在這個快速變遷的時代，這樣。"
    assert not out["a"]["passed"] and out["b"]["passed"]
    assert out["a"]["text"].startswith("> ⚠") is False       # the header is added by the writer of the file
    from ant_peer_review.gate import with_header
    assert with_header(out["a"], t).startswith("> ⚠") and "快速變遷" in with_header(out["a"], t)
    assert with_header(out["b"], t) == out["b"]["text"]
    md = checks_md(out, t, "回覆")
    assert "a" in md and "b" in md and "stock_phrase" in md and "✓" in md and "✗" in md


# @S-writing-gate-006
def test_judge_other_model_and_quotes():
    assert judge_model(["opus", "sonnet"], "opus") == "sonnet"
    assert judge_model(["opus"], "opus") == "opus"
    text = "這篇文章很棒。它提供了很多有價值的內容。"
    b = ScriptBackend({("*", "judge"): {"verdicts": [{"key": "a", "checks": [
        {"name": "filler", "pass": False, "evidence": "它提供了很多有價值的內容"},
        {"name": "hook", "pass": False, "evidence": ""},
        {"name": "human_like", "pass": False, "evidence": "not in the text"}]}]}})
    got = judge(b, "sonnet", {"a": text}, voice="")
    assert b.calls[0]["model"] == "sonnet"
    assert [(i["code"], i["level"]) for i in got["a"]] == [("judge:filler", "strong")]
    assert "它提供了很多有價值的內容" in got["a"][0]["detail"]
    assert "lecturing" in JUDGE_SYSTEM
    b = ScriptBackend({("*", "judge"): {"verdicts": [{"key": "a", "checks": [
        {"name": "lecturing", "pass": False, "evidence": "它提供了很多有價值的內容"}]}]}})
    got = judge(b, "sonnet", {"a": text}, voice="")
    assert [(i["code"], i["level"]) for i in got["a"]] == [("judge:lecturing", "weak")]


# @S-writing-gate-008
def test_halfwidth_punctuation_in_chinese():
    bad = "K8s 入門系列,先會 Docker,再走四個階段:從部署到安全。"
    assert "halfwidth_punctuation" in codes(rule_check(bad), "hard")
    ok = "K8s 入門系列，成本 1,000 元，詳見 https://ex.example/a?x=1,2:3 。"
    assert "halfwidth_punctuation" not in codes(rule_check(ok))


# @S-writing-gate-009
def test_fixup_changes_what_needs_no_judgment():
    from ant_peer_review.platforms import load_platforms
    text, changes = autofix("值得一提的是，K8s 入門系列,先會 Docker。")
    assert text == "K8s 入門系列，先會 Docker。"
    assert any("halfwidth" in c for c in changes) and any("值得一提的是" in c for c in changes)
    ig = load_platforms()["instagram"]
    text, changes = autofix("**重點** 好文 #a #b #c #d #e #f #g", platform=ig)
    assert text == "重點 好文 #a #b #c #d #e"
    assert "removed Markdown" in changes and "hashtags 7 → 5" in changes
    assert autofix("該上 K8s 了」? 好")[0] == "該上 K8s 了」？ 好"
    assert autofix("自動化(服務發現、Helm)和 API (v2)")[0] == "自動化（服務發現、Helm）和 API (v2)"
    assert autofix("- Workloads (工作負載介紹)")[0] == "- Workloads (工作負載介紹)"   # a term and its gloss
    url = "https://ex.example/a?x=1,2:3"
    assert autofix(f"好文,看這裡 {url}")[0] == f"好文，看這裡 {url}"      # URLs untouched
    out = run_gate({"a": "值得一提的是，這篇寫得清楚。"}, lambda f: {},
                   check=lambda k, text: rule_check(text))
    assert out["a"]["passed"] and out["a"]["rounds"] == 0
    assert "值得一提的是" in checks_md(out, t, "x")


# @S-writing-gate-010
def test_strong_or_two_weak_start_an_edit():
    bullets = "🚀 一\n✅ 二\n🔥 三"
    para = "這段話有二十個字左右，長度都很接近彼此差不多。"
    two_weak = bullets + "\n\n" + "\n\n".join([para] * 4)
    strong = "說到底，問題在結構。"
    assert not needs_edit(rule_check(bullets)) and needs_edit(rule_check(two_weak))
    assert needs_edit(rule_check(strong))
    seen = []
    run_gate({"one": "流程要先理順。真的就是這樣，對吧，" + "很長的一句話" * 3,
              "two": "🚀 一\n✅ 二\n🔥 三\n賦能大家。", "three": strong},
             lambda f: seen.extend(f) or {}, check=lambda k, text: rule_check(text))
    assert sorted(set(seen)) == ["three", "two"]


# @S-writing-gate-011
def test_hollow_contrast_only():
    assert "hollow_contrast" in codes(rule_check("這不是技巧，而是心態。"), "strong")
    assert "hollow_contrast" not in codes(rule_check("這不是加機器，而是把查詢從 3 秒降到 0.2 秒。"))
    assert "hollow_contrast" in codes(rule_check("It's not about tactics, it's about mindset."))
    for text in ("所以我覺得要管的是 AI「默默改變做法」，不是創新本身。", "It's a habit, not a tool."):
        assert "hollow_contrast" in codes(rule_check(text), "strong"), text
    assert "hollow_contrast" not in codes(rule_check("瓶頸是 3 秒的查詢，不是機器。"))
    assert "hollow_contrast" in codes(rule_check("我覺得不必禁止它改做法，該禁止的是它沒先講就改。"), "strong")
    assert "hollow_contrast" not in codes(rule_check("不必背公式，要記的是 3 個數字。"))
    for text in ("我還是會去，不是因為怕。", "但是很多人，不是每個人都懂。"):   # 還是 / 但是 are words
        assert "hollow_contrast" not in codes(rule_check(text)), text


# @S-writing-gate-012
def test_quotes_and_title_are_not_tells():
    text = "作者提醒別寫「值得一提的是」這種開頭。推薦〈說到底，K8s 是什麼〉。"
    assert codes(rule_check(text, protect=["說到底，K8s 是什麼"])) == []
    assert "deep_saying" in codes(rule_check(text))


# @S-writing-gate-013
def test_edits_keep_facts():
    url = "https://ex.example/a"
    issues = verify_facts("營收成長 60%，好文。", before=f"營收成長 40%，好文 {url}",
                          sources="Revenue grew 40% in 2025")
    assert ("unsupported_detail", "60%") in [(i["code"], i["detail"]) for i in issues]
    assert "lost_link" in codes(issues, "hard")
    assert "adding none" in EDIT_RULES and "keeping every supported claim" in EDIT_RULES
    calls = []

    def rewrite(failed):
        calls.append(failed)
        return {"a": "營收成長 60%，好文。"}

    run_gate({"a": f"說到底，營收成長 40% {url}"}, rewrite, check=lambda k, text: rule_check(text),
             sources="Revenue grew 40% in 2025")
    assert len(calls) == 2
    assert any("unsupported_detail: 60%" in r for r in calls[1]["a"]["reasons"])
    assert any("lost_link" in r for r in calls[1]["a"]["reasons"])


# @S-writing-gate-014
def test_staging_tells_in_both_languages():
    cases = {"真正的問題是預算。": "deep_saying", "讓我們來看看細節。": "run_up",
             "我不是說這不好。": "straw_man", "希望這對你有幫助！": "chatbot_residue",
             "The real question is budget.": "deep_saying", "Here's the thing: it works.": "run_up",
             "I'm not saying it's bad.": "straw_man", "I hope this helps.": "chatbot_residue",
             "有人會說這樣綁手綁腳。": "straw_man", "你可能會覺得這很麻煩。": "straw_man",
             "Some might say it slows you down.": "straw_man",
             "先補一點背景。穹窿體是顆粒。": "run_up", "先交代一下背景：這是預印本。": "run_up", "先說背景：這是預印本。": "run_up",
             "Some background first: it is a preprint.": "run_up",
             "先說清楚成果的範圍。這是預印本。": "run_up",
             "同一個專案裡剛好有三種結果。成功的那次很快。": "run_up", "幾個但書。這是預印本。": "run_up",
             "這是我看一個實驗室的紀錄後想到的。": "this_is_recap",
             "「先照正常做法來」聽起來會壓掉 AI 的創意，可是這次加速來自偏離。": "straw_man"}
    for text, code in cases.items():
        assert code in codes(rule_check(text), "strong"), text



# @S-writing-gate-015
def test_blocks_and_dashes_removed_everywhere():
    text = "重點 ▋ 先看結果——再談方法。2020–2025 年，「原文——引述」不動。"
    out, changes = autofix(text)
    assert out == "重點 先看結果，再談方法。2020-2025 年，「原文——引述」不動。", out
    assert changes
    assert not any("dash" in c for c in autofix("他說「重點在這裡」。")[1])
    assert autofix("共 1,000 人 — 不少")[0] == "共 1,000 人，不少"
    assert autofix("共 1,000 人 — 不少", punct="casual")[0] == "共 1,000 人, 不少"
    for ch in "▋▌█■▮":
        assert "block_char" in codes(rule_check(f"重點{ch}結果。"), "hard"), ch


# @S-writing-gate-016
def test_casual_punctuation():
    text = "先看結果，再談方法；重點是「迴圈」（不是能力）。真的嗎？是的！\n下一段：結束。"
    out, changes = autofix(text, punct="casual")
    assert out == '先看結果, 再談方法, 重點是 "迴圈" (不是能力)。真的嗎? 是的!\n下一段: 結束。', out
    # the user's case: a sentence end next to Latin text keeps its mark
    assert autofix("可以用超過 256 位元組的密碼登入。OpenSSH 10.6p2 已經推出", punct="casual")[0] \
        == "可以用超過 256 位元組的密碼登入。OpenSSH 10.6p2 已經推出"
    assert codes(rule_check("先看結果, 再談。真的嗎?", punct="casual"), "hard") == []
    # a half-width mark the model wrote gets its space; numbers, URLs and closing marks do not
    assert autofix('鎖定帳號,例如 root;還有:這些!真的?是', punct="casual")[0] == \
        "鎖定帳號, 例如 root; 還有: 這些! 真的? 是"
    assert autofix("共 1,000 人,10:30 開始,見 https://ex.example/a?b=1,2", punct="casual")[0] == \
        "共 1,000 人, 10:30 開始, 見 https://ex.example/a?b=1,2"
    assert autofix('他說 "好,"\n下一行:\n結束?)', punct="casual")[0] == '他說 "好,"\n下一行:\n結束?)'
    assert "fullwidth_punctuation" in codes(rule_check("先看結果，再談。", punct="casual"), "hard")
    assert codes(rule_check("先看結果, 再談方法 真的嗎?", punct="casual"), "hard") == []
    assert "halfwidth_punctuation" in codes(rule_check("先看結果,再談方法。"), "hard")
    assert autofix("K8s 入門系列,先會 Docker。")[0] == "K8s 入門系列，先會 Docker。"


# @S-writing-gate-017
def test_chinese_phrasing_tells_are_weak():
    cases = {"我們會進行深入的討論。": "jinxing_verb", "隨著人工智慧的快速發展，工作變了。": "suizhe_opener",
             "公司的產品的設計的問題很多。": "stacked_de", "先試；再看。然後改；最後發。": "semicolons"}
    for text, code in cases.items():
        issues = rule_check(text)
        assert code in codes(issues, "weak"), text
        assert code not in codes(issues, "strong") + codes(issues, "hard"), text
    for text in ("先試；再看。", "專案還在進行中。", "隨著時間過去，大家習慣了。", "隨著他發展出新方法，進度變快。", "我的書和你的筆都在桌上。"):
        assert not {"jinxing_verb", "suizhe_opener", "stacked_de", "semicolons"} & set(codes(rule_check(text), "weak")), text
    assert "semicolons" not in codes(rule_check("先試；再看。然後改；最後發。", punct="casual"), "weak")


# @S-writing-gate-018
def test_quote_then_this_is_strong():
    for text in ("「除非行不通，否則先照正常做法來。」這是一個研究團隊用 Claude 解析結構時說的話。",
                 "背景如下。「先照正常做法來」這就是他們的原則。", "“先照正常做法来”这是团队说的话。",
                 "「除非行不通，否則先照正常做法來。」這句話是一個研究團隊對 Claude 說的。",
                 "「除非行不通，否則先照正常做法來。」一個研究團隊用 Claude 解析結構，在處理資料的階段，對 AI 說了這句話。",
                 "「先照正常做法來」，這是研究團隊的原則。"):
        assert "quote_then_this" in codes(rule_check(text), "strong"), text
    for text in ("研究團隊借助 Claude 解析結構時，提出一個簡單原則：「除非行不通，否則先照正常做法來。」",
                 "「除非行不通，否則先照正常做法」- 研究團隊引導 Claude 的核心原則",
                 "他說「好」，這是第一次。", "他說「好」這是第一次。", "「好。」他說完就走了。"):
        assert "quote_then_this" not in codes(rule_check(text)), text
    assert "who said it" in EDIT_RULES
    from ant_peer_review.share import SYSTEM as SHARE_SYSTEM
    assert "who said it" in SHARE_SYSTEM


# @S-writing-gate-019
def test_sweeping_claim_and_personified_error():
    issues = rule_check("代價最高的錯誤都是悄悄發生的。")
    assert "sweeping_claim" in codes(issues, "strong")
    assert "personified_error" in codes(issues, "weak")
    assert "personified_error" in codes(rule_check("還有一次更安靜：添加劑擋住了 DNA。"), "weak")
    for text in ("最高的山在亞洲。", "他悄悄改掉錯誤。", "問題很安全。", "先說他的看法，再看數據。", "我喜歡這種做法。",
                 "這首歌聽起來不錯。"):
        got = set(codes(rule_check(text)))
        assert not {"sweeping_claim", "personified_error", "run_up", "straw_man"} & got, text
    assert "no more than its cases show" in EDIT_RULES


# @S-writing-gate-020
def test_clickbait_headline_is_strong():
    for text in ("震驚！研究團隊竟然這樣用 AI\n\n內文。", "You won't believe what Claude found\n\nBody."):
        assert "clickbait" in codes(rule_check(text), "strong"), text
    for text in ("研究團隊讓 Claude 先講再改\n\n後來大家都很震驚。", "他說「你絕對想不到」，然後走了。"):
        assert "clickbait" not in codes(rule_check(text)), text
    assert "clickbait" in JUDGE_SYSTEM
    b = ScriptBackend({("*", "judge"): {"verdicts": [{"key": "a", "checks": [
        {"name": "clickbait", "pass": False, "evidence": "研究團隊"}]}]}})
    got = judge(b, "sonnet", {"a": "研究團隊讓 Claude 先講再改。"}, voice="")
    assert [(i["code"], i["level"]) for i in got["a"]] == [("judge:clickbait", "strong")]


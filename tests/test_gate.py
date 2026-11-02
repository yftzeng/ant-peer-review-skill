import json

from ant_peer_review.gate import checks_md, judge, judge_model, rule_check, run_gate
from ant_peer_review.i18n import T
from ant_peer_review.platforms import count, load_platforms
from helpers import ScriptBackend

t = T("zh-TW")


def codes(issues, level=None):
    return [i["code"] for i in issues if level is None or i["level"] == level]


# @S-writing-gate-001
def test_stock_phrases_with_allow_and_deny():
    text = "在這個快速變遷的時代，值得一提的是這篇文章。"
    hard = [i for i in rule_check(text) if i["level"] == "hard"]
    assert codes(hard) == ["stock_phrase", "stock_phrase"]
    assert any("在這個快速變遷的時代" in i["detail"] for i in hard)
    hard = [i for i in rule_check(text, allow=["值得一提的是"]) if i["level"] == "hard"]
    assert len(hard) == 1 and "快速變遷" in hard[0]["detail"]
    assert codes(rule_check("這篇寫得很扎實。", deny=["扎實"]), "hard") == ["stock_phrase"]
    assert codes(rule_check("We delve into the data.")) == ["stock_phrase"]


# @S-writing-gate-002
def test_structural_tells_are_soft():
    text = "不是工具的問題，而是流程的問題——真的——就是這樣——。不是快，而是穩。\n🚀 一\n✅ 二\n🔥 三"
    issues = rule_check(text)
    assert codes(issues, "hard") == []
    assert {"dashes", "not_but", "emoji_bullets"} <= set(codes(issues, "soft"))
    para = "這段話有二十個字左右，長度都很接近彼此差不多。"
    issues = rule_check("\n\n".join([para] * 4))
    assert codes(issues, "hard") == [] and "uniform_paragraphs" in codes(issues, "soft")
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
        return {k: "總而言之，還是這樣。" for k in failed}

    out = run_gate({"a": "總而言之，這樣。", "b": "這篇寫得很清楚。"}, rewrite,
                   check=lambda k, text: rule_check(text))
    assert len(calls) == 2 and all(list(c) == ["a"] for c in calls)
    assert "stock_phrase" in calls[0]["a"]["reasons"][0] and calls[0]["a"]["text"] == "總而言之，這樣。"
    assert not out["a"]["passed"] and out["b"]["passed"]
    assert out["a"]["text"].startswith("> ⚠") is False       # the header is added by the writer of the file
    from ant_peer_review.gate import with_header
    assert with_header(out["a"], t).startswith("> ⚠") and "總而言之" in with_header(out["a"], t)
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
    assert [(i["code"], i["level"]) for i in got["a"]] == [("judge:filler", "hard")]
    assert "它提供了很多有價值的內容" in got["a"][0]["detail"]

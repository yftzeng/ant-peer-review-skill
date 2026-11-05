import json

import pytest

from ant_peer_review.i18n import LOCALE_DIR, T
from ant_peer_review.onboarding import banner, choose_models, effective_models, first_use
from ant_peer_review.store import PACKAGE_DIR, Config, Store, default_home
from ant_peer_review.ui import ScriptedIO
from conftest import ProbeBackend


# @S-user-setup-001
def test_first_use_preselects_opus_and_sonnet(store):
    io = ScriptedIO(["", "", ""])  # default language, default backend, confirm checkbox
    cfg = first_use(io, store, lambda name: ProbeBackend())
    assert cfg.models == ["opus", "sonnet"]
    assert store.load_config().models == ["opus", "sonnet"]
    assert "[x] opus" in io.text and "[x] sonnet" in io.text and "[ ] fable" in io.text


# @S-user-setup-002
def test_no_reviewer_is_refused(store):
    io = ScriptedIO(["1 2", "", "1 2", ""])  # untick both, confirm (refused), tick both, confirm
    got = choose_models(io, Config(), ProbeBackend())
    assert "at least 1" in io.text
    assert got == ["opus", "sonnet"]
    title = T("en")("setup.models")
    assert "2" in title and "at least" not in title


# @S-user-setup-009
def test_single_reviewer_needs_confirmation(store):
    # untick sonnet, confirm, choose again (re-shown from the saved choice), untick, confirm, go on
    io = ScriptedIO(["2", "", "n", "2", "", "y"])
    cfg = Config()
    got = choose_models(io, cfg, ProbeBackend())
    assert "no cross-review" in io.text
    assert got == ["opus"] and cfg.models == ["opus"]


# @S-user-setup-003
def test_banner_lists_models_and_command():
    line = banner(T("en"), ["opus", "fable"])
    assert "Peer reviewers: opus, fable" in line
    assert "ant-peer-review config models" in line


# @S-user-setup-004
def test_config_models_starts_from_saved_choice(store):
    cfg = Config(models=["opus", "fable"])
    io = ScriptedIO(["2", ""])  # tick sonnet, confirm
    choose_models(io, cfg, ProbeBackend())
    store.save_config(cfg)
    assert "[x] opus" in io.out[1] and "[ ] sonnet" in io.out[2] and "[x] fable" in io.out[3]
    assert store.load_config().models == ["opus", "sonnet", "fable"]


# @S-user-setup-005
def test_failed_probe_is_not_saved(store):
    cfg = Config()
    io = ScriptedIO(["3", ""])  # tick fable too, confirm
    got = choose_models(io, cfg, ProbeBackend(down={"fable"}))
    assert got == ["opus", "sonnet"]
    assert "fable" in io.text and "unavailable" in io.text


# @S-user-setup-006
def test_strings_follow_language_and_keys_match():
    assert T("zh-TW")("setup.models").startswith("Peer reviewer 模型")
    en = json.loads((LOCALE_DIR / "en.json").read_text())
    for lang in ("zh-TW", "zh-CN"):
        other = json.loads((LOCALE_DIR / f"{lang}.json").read_text())
        assert set(en) == set(other), (lang, set(en) ^ set(other))
        for k, v in en.items():
            import string
            fields = {f for _, f, _, _ in string.Formatter().parse(v) if f}
            ofields = {f for _, f, _, _ in string.Formatter().parse(other[k]) if f}
            assert fields == ofields, (lang, k)


# @S-user-setup-007
def test_override_does_not_change_saved(store):
    store.save_config(Config(models=["opus", "sonnet"]))
    cfg = store.load_config()
    assert effective_models(cfg, "opus,fable") == ["opus", "fable"]
    assert store.load_config().models == ["opus", "sonnet"]
    with pytest.raises(ValueError):  # one reviewer is allowed (S-user-setup-010); none is not
        effective_models(cfg, ",")


# @N-user-setup-001
def test_store_never_inside_package(monkeypatch):
    monkeypatch.setenv("ANT_PEER_REVIEW_HOME", str(PACKAGE_DIR / "data"))
    with pytest.raises(RuntimeError):
        default_home()


def test_unavailable_backend_is_refused(store):
    io = ScriptedIO(["", "2", "1", ""])  # lang default, pick anthropic-api (refused), claude-cli, models
    cfg = first_use(io, store, lambda name: ProbeBackend())
    assert cfg.backend == "claude-cli" and "not available yet" in io.text


# @S-user-setup-008
def test_questions_info_and_phases_are_distinct():
    from ant_peer_review.ui import phase_line, radio
    io = ScriptedIO([""])
    radio(io, T("zh-TW"), "目的：", [("a", "A"), ("b", "B")], default="a")
    assert io.out[0].startswith("\n? 目的：")
    assert io.out[-1].startswith("› ")
    b = banner(T("zh-TW"), ["opus", "sonnet"])
    first, second = b.split("\n")
    assert first.startswith("ℹ ") and "opus, sonnet" in first
    assert "ant-peer-review config models" in second and "ant-peer-review" not in first
    line = phase_line(T("zh-TW")("run.phase_start", phase="intake"))
    assert line.startswith("\n━━") and "intake" in line
    assert "\x1b[" not in b + io.text + line


# @S-user-setup-010
def test_single_reviewer_override_warns():
    from ant_peer_review.onboarding import parse_models_override
    assert parse_models_override("opus") == ["opus"]
    assert "no cross-review" in banner(T("en"), ["opus"])
    assert "no cross-review" not in banner(T("en"), ["opus", "sonnet"])


# @S-user-setup-011
import pytest as _pytest


@_pytest.mark.parametrize("env,lang", [
    ({"LANG": "zh_TW.UTF-8"}, "zh-TW"), ({"LC_ALL": "zh_HK.UTF-8", "LANG": "en_US.UTF-8"}, "zh-TW"),
    ({"LANGUAGE": "zh_Hant"}, "zh-TW"), ({"LANG": "zh_CN.UTF-8"}, "zh-CN"),
    ({"LC_MESSAGES": "zh_SG", "LANG": "zh_TW"}, "zh-CN"), ({"LANG": "zh"}, "zh-CN"),
    ({"LANG": "C.UTF-8"}, "en"), ({"LANG": "en_US.UTF-8"}, "en"), ({}, "en"),
    ({"LC_ALL": "", "LANG": "zh_TW.UTF-8"}, "zh-TW")])
def test_first_use_language_from_the_system(tmp_path, monkeypatch, env, lang):
    from ant_peer_review.store import Store, system_lang
    for k in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert system_lang() == lang
    store = Store(tmp_path / "home")
    assert store.load_config().lang == lang
    (tmp_path / "home").mkdir(exist_ok=True)
    store.config_path.write_text('lang = "en"\n', encoding="utf-8")
    assert store.load_config().lang == "en"          # a saved language always wins

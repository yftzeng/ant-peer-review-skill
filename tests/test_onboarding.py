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
def test_fewer_than_two_is_refused(store):
    io = ScriptedIO(["2", "", "3", ""])  # untick sonnet, confirm (refused), tick fable, confirm
    cfg = Config()
    got = choose_models(io, cfg, ProbeBackend())
    assert "at least 2" in io.text
    assert got == ["opus", "fable"]


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
    with pytest.raises(ValueError):
        effective_models(cfg, "opus")


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

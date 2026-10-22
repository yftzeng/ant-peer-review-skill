import pytest

from ant_peer_review.i18n import T
from ant_peer_review.intake import (ask_audience, build_intake_from_args, collect_targets)
from ant_peer_review.ui import ScriptedIO

t = T("en")


# @S-intake-001
def test_targets_classified_and_echoed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes").mkdir()
    io = ScriptedIO(["https://example.com/a", "notes", "Some pasted text", "/done"])
    got = collect_targets(io, t)
    assert [x["kind"] for x in got] == ["url", "path", "text"]
    assert got[1]["value"] == str(tmp_path / "notes")
    assert "#1" in io.text and "#2" in io.text and "#3" in io.text


# @S-intake-002
def test_two_empty_lines_or_eof_end():
    assert len(collect_targets(ScriptedIO(["https://example.com/a", "", ""]), t)) == 1
    assert len(collect_targets(ScriptedIO(["https://example.com/a"]), t)) == 1


# @S-intake-003
def test_consecutive_text_lines_merge():
    got = collect_targets(ScriptedIO(["Line one", "Line two", "/done"]), t)
    assert got == [{"kind": "text", "value": "Line one\nLine two"}]


# @S-intake-004
def test_empty_list_asks_again():
    io = ScriptedIO(["/done", "https://example.com/a", "/done"])
    got = collect_targets(io, t)
    assert "at least one target" in io.text
    assert got == [{"kind": "url", "value": "https://example.com/a"}]


# @S-intake-005
def test_audience_layers_custom_and_skip():
    io = ScriptedIO(["4", "s", "c", "regulators", "1", "3", "1"])
    aud = ask_audience(io, t)
    assert aud == {"expertise": "expert", "role": None, "lens": "custom:regulators",
                   "trust": "stranger", "purpose": "trend"}
    assert "regulators" in io.text  # shown on the card


# @S-intake-006
def test_audience_card_edit():
    io = ScriptedIO(["4", "s", "s", "s", "s", "2", "2", "1"])
    aud = ask_audience(io, t)
    assert aud["expertise"] == "beginner"


# @S-intake-007
def test_non_interactive_intake():
    got = build_intake_from_args("audit", ["https://example.com/a", "plain text"],
                                 "expertise=expert,purpose=trend", lang="en")
    assert got["purpose"] == "audit"
    assert got["targets"] == [{"kind": "url", "value": "https://example.com/a"},
                              {"kind": "text", "value": "plain text"}]
    assert got["audience"] == {"expertise": "expert", "role": None, "lens": None,
                               "trust": None, "purpose": "trend"}


# @N-intake-001
@pytest.mark.parametrize("bad", ["level=expert", "expertise=guru"])
def test_unknown_audience_rejected(bad):
    with pytest.raises(ValueError):
        build_intake_from_args("audit", ["x"], bad, lang="en")


def test_custom_audience_from_args():
    got = build_intake_from_args("drafting", ["x"], "lens=custom:regulators", lang="en")
    assert got["audience"]["lens"] == "custom:regulators"

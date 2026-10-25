import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ant_peer_review.i18n import T
from ant_peer_review.ui import ScriptedIO, checkbox, disp_width, radio, render_menu, MenuState

t = T("en")


class FakeTerm:
    """A terminal-capable IO fed with key tokens and typed lines."""

    def __init__(self, keys, texts=(), cols=80):
        self.keys, self.texts, self.cols = list(keys), list(texts), cols
        self.buf, self.out = [], []

    def interactive(self):
        return True

    def columns(self):
        return self.cols

    def read_key(self):
        if not self.keys:
            raise EOFError
        return self.keys.pop(0)

    def write(self, s):
        self.buf.append(s)

    def say(self, text=""):
        self.out.append(text)
        self.buf.append(text + "\n")

    def ask(self, prompt):
        self.buf.append(prompt)
        return self.texts.pop(0)

    @property
    def screen(self):
        return "".join(self.buf)


PURPOSE = [("audit", "Audit"), ("drafting", "Drafting")]
MODELS = [("opus", "opus"), ("sonnet", "sonnet"), ("fable", "fable")]


# @S-menus-001
def test_down_enter_picks_second():
    assert radio(FakeTerm(["down", "enter"]), t, "Purpose:", PURPOSE, default="audit") == "drafting"


def test_up_wraps_and_number_selects():
    assert radio(FakeTerm(["up", "enter"]), t, "P:", PURPOSE, default="audit") == "drafting"
    assert radio(FakeTerm(["2"]), t, "P:", PURPOSE, default="audit") == "drafting"


# @S-menus-002
def test_space_and_numbers_toggle():
    got = checkbox(FakeTerm(["down", "space", "3", "enter"]), t, "Models:", MODELS, ["opus"])
    assert got == ["opus", "sonnet", "fable"]


# @S-menus-003
def test_c_adds_custom():
    term = FakeTerm(["c", "enter"], texts=["regulators"])
    got = checkbox(term, t, "(c) Lens:", [("consumer", "Consumer")], [], allow_custom=True)
    assert got == ["custom:regulators"]


# @S-menus-004
def test_min_selected_reason_then_stays():
    term = FakeTerm(["enter", "down", "space", "enter"])
    got = checkbox(term, t, "Models:", MODELS, ["opus"], min_selected=2)
    assert got == ["opus", "sonnet"]
    assert term.screen.count("at least 2") >= 1


# @S-menus-005
def test_collapses_to_summary():
    term = FakeTerm(["enter"])
    radio(term, t, "Purpose:", PURPOSE, default="audit")
    assert "\x1b[J" in term.screen                     # menu erased in place
    assert term.screen.rstrip().endswith("? Purpose: Audit")


# @S-menus-006
def test_esc_cancels():
    with pytest.raises(KeyboardInterrupt):
        radio(FakeTerm(["esc"]), t, "Purpose:", PURPOSE, default="audit")


# @S-menus-007
def test_wide_labels_cut_to_width():
    st = MenuState(values=["a"], labels=["測" * 30], multi=False, cursor=0, chosen=[])
    for line in render_menu(st, "標題：" * 10, t, width=20):
        assert disp_width(line) <= 20


# @N-menus-001
def test_plain_io_never_reads_keys():
    io = ScriptedIO(["2"])
    assert radio(io, t, "Purpose:", PURPOSE, default="audit") == "drafting"
    assert not hasattr(io, "read_key")


# @S-menus-008
@pytest.mark.skipif(sys.platform == "win32", reason="pty is POSIX only")
def test_real_pty_arrow_keys(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text('lang = "en"\nbackend = "claude-cli"\nmodels = ["opus", "sonnet"]\n')
    env = dict(os.environ, ANT_PEER_REVIEW_HOME=str(home), TERM="xterm",
               PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    env.pop("NO_COLOR", None)
    # openpty + Popen instead of pty.fork(): forking a multi-threaded pytest can deadlock.
    fd, slave = os.openpty()
    proc = subprocess.Popen([sys.executable, "-m", "ant_peer_review", "--backend", "fake"],
                            stdin=slave, stdout=slave, stderr=slave, env=env,
                            start_new_session=True)
    os.close(slave)
    seen = b""

    def wait_for(marker, timeout=15):
        nonlocal seen
        end = time.time() + timeout
        while marker.encode() not in seen:
            if time.time() > end:
                raise AssertionError(f"never saw {marker!r}; tail: {seen[-400:]!r}")
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                try:
                    seen += os.read(fd, 65536)
                except OSError:
                    break
        seen_at = seen.index(marker.encode()) + len(marker)
        seen = seen[seen_at:]

    try:
        wait_for("Purpose:")
        time.sleep(0.2)
        os.write(fd, b"\x1b[B")
        time.sleep(0.2)
        os.write(fd, b"\r")
        wait_for("Enter targets")
        os.write(fd, b"hello world text\n/done\n")
        for layer in ("(a) Expertise", "(b) Decision", "(c) Industry", "(d) Trust", "(e) Reading"):
            wait_for(layer)
            time.sleep(0.15)
            os.write(fd, b"\r")
        wait_for("Audience card")
        time.sleep(0.15)
        os.write(fd, b"\r")
        wait_for("Extra fact-check sources")
        time.sleep(0.15)
        os.write(fd, b"\r")
        wait_for("Brand")
        os.write(fd, b"\n")
        wait_for("Phase sources")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        os.close(fd)
    run = next((home / "runs").iterdir())
    assert json.loads((run / "00-intake.json").read_text())["purpose"] == "drafting"


MANY = [(f"o{i}", f"Option {i}") for i in range(1, 24)]


# @S-menus-009
def test_checkbox_pages_keep_ticks():
    term = FakeTerm(["space", "right", "space", "left", "enter"])
    got = checkbox(term, t, "Articles:", MANY, [], page_size=10)
    assert got == ["o1", "o11"]
    frames = [f for f in term.screen.split("\x1b[J") if "Articles:" in f]
    assert all(sum(1 for ln in f.splitlines() if "Option " in ln) <= 10 for f in frames[:-1])
    assert "page 1/3" in term.screen and "page 2/3" in term.screen
    st = MenuState(values=[v for v, _ in MANY], labels=[lb for _, lb in MANY], multi=True,
                   cursor=22, chosen=[], page_size=10)
    lines = render_menu(st, "Articles:", t, 80)
    assert sum("Option " in ln for ln in lines) == 3 and any("page 3/3" in ln for ln in lines)


# @S-menus-010
def test_line_mode_pages_with_global_numbers():
    io = ScriptedIO(["n", "12", ""])
    got = checkbox(io, t, "Articles:", MANY, [], page_size=10)
    assert got == ["o12"]
    assert "11) [ ] Option 11" in io.text and "20) [ ] Option 20" in io.text
    first_page = io.text.split("page 2/3")[0]
    assert "Option 11" not in first_page and "10) [ ] Option 10" in first_page

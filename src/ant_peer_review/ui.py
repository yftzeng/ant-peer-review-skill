"""Terminal interaction: radio, checkbox, free text, multi-line target entry.

All prompts go through an IO object so tests can script the answers.
"""
from __future__ import annotations

import os
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from .i18n import T

END_TOKENS = {"/done"}


# ---- styling: symbols always, ANSI colour only on a real terminal ------------
def _use_color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR") \
        and os.environ.get("TERM") != "dumb"


def _c(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _use_color() else text


def question(text: str) -> str:
    """A question opens a new block so consecutive questions never run together."""
    return "\n" + _c("1;36", "? " + text)


def prompt(text: str) -> str:
    return _c("36", "› ") + text + " "


def info(text: str) -> str:
    return _c("33", "ℹ " + text)


def warn(text: str) -> str:
    return _c("33", "⚠ " + text)


def dim(text: str) -> str:
    return _c("2", text)


def section(text: str) -> str:
    return "\n" + _c("1", text)


def ask_text(io: "IO", title: str) -> str:
    """A free-text question: its own block, then a bare input marker."""
    io.say(question(title))
    return io.ask(_c("36", "› "))


def phase_line(text: str) -> str:
    return "\n" + _c("1;35", f"━━ {text} ━━")


class IO(Protocol):
    def say(self, text: str = "") -> None: ...
    def ask(self, prompt: str) -> str: ...  # raises EOFError on Ctrl-D


class ConsoleIO:
    def say(self, text: str = "") -> None:
        print(text, flush=True)

    def ask(self, prompt: str) -> str:
        return input(prompt)

    # ---- arrow-key menus (only on a real terminal) ----
    def interactive(self) -> bool:
        return (sys.stdin.isatty() and sys.stdout.isatty()
                and os.environ.get("TERM") != "dumb"
                and not os.environ.get("ANT_PEER_REVIEW_PLAIN"))

    def columns(self) -> int:
        return shutil.get_terminal_size((80, 24)).columns

    def write(self, s: str) -> None:
        sys.stdout.write(s)
        sys.stdout.flush()

    def read_key(self) -> str:
        return read_key_windows() if sys.platform == "win32" else read_key_posix()


_ESC_SEQ = {"[A": "up", "[B": "down", "OA": "up", "OB": "down", "[C": "right", "[D": "left"}


def read_key_posix() -> str:
    """One key in cbreak mode (Ctrl-C still raises). TCSANOW: never drop typed-ahead input."""
    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd, termios.TCSANOW)
        ch = os.read(fd, 1)
        if not ch:
            raise EOFError
        if ch == b"\x1b":
            seq = b""
            while len(seq) < 2 and select.select([fd], [], [], 0.05)[0]:
                seq += os.read(fd, 1)
            return _ESC_SEQ.get(seq.decode("ascii", "replace"), "esc" if not seq else "other")
        if ch in (b"\r", b"\n"):
            return "enter"
        if ch == b" ":
            return "space"
        if ch == b"\x04":
            raise EOFError
        if ch[0] >= 0x80:  # rest of a UTF-8 character
            while select.select([fd], [], [], 0.01)[0] and len(ch) < 4:
                ch += os.read(fd, 1)
        return ch.decode("utf-8", "replace")
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, old)


def read_key_windows() -> str:  # pragma: no cover - no Windows CI here
    import msvcrt
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(msvcrt.getwch(), "other")
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch == "\x1a":
        raise EOFError
    return {"\r": "enter", "\n": "enter", " ": "space", "\x1b": "esc"}.get(ch, ch)


# ---- menu state and drawing (pure, testable without a terminal) -------------
_ANSI = __import__("re").compile(r"\x1b\[[0-9;]*[A-Za-z]")


def disp_width(s: str) -> int:
    w = 0
    for ch in _ANSI.sub("", s):
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def cut(s: str, width: int) -> str:
    """Cut plain text to a display width, marking the cut with an ellipsis."""
    if disp_width(s) <= width:
        return s
    out, w = "", 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > width - 1:
            break
        out += ch
        w += cw
    return out + "…"


@dataclass
class MenuState:
    values: list
    labels: list[str]
    multi: bool
    cursor: int
    chosen: list
    custom: bool = False      # a "+ custom…" row and the c key
    skip: bool = False        # radio only: a "skip" row
    message: str = ""

    def rows(self) -> list:
        extra = (["__custom__"] if self.custom else []) + (["__skip__"] if self.skip else [])
        return list(self.values) + extra

    def handle(self, key: str):
        """Returns None (keep going) or (action, value): select / confirm / custom / cancel."""
        rows = self.rows()
        self.message = ""
        if key in ("up", "k"):
            self.cursor = (self.cursor - 1) % len(rows)
        elif key in ("down", "j"):
            self.cursor = (self.cursor + 1) % len(rows)
        elif key.isdigit() and 1 <= int(key) <= len(self.values):
            i = int(key) - 1
            if not self.multi:
                return ("select", self.values[i])
            self.cursor = i
            self._toggle(self.values[i])
        elif key == "space" and self.multi and self.cursor < len(self.values):
            self._toggle(self.values[self.cursor])
        elif key.lower() == "c" and self.custom:
            return ("custom", None)
        elif key == "esc":
            return ("cancel", None)
        elif key == "enter":
            row = rows[self.cursor]
            if row == "__custom__":
                return ("custom", None)
            if row == "__skip__":
                return ("select", None)
            return ("confirm", list(self.chosen)) if self.multi else ("select", row)
        return None

    def _toggle(self, v) -> None:
        if v in self.chosen:
            self.chosen.remove(v)
        else:
            self.chosen.append(v)
        self.chosen.sort(key=self.values.index)


def render_menu(st: MenuState, title: str, t: T, width: int) -> list[str]:
    lines = ["", _c("1;36", cut("? " + title, width))]
    for i, row in enumerate(st.rows()):
        cur = i == st.cursor
        if row == "__custom__":
            label = "+ " + t("ui.custom")
        elif row == "__skip__":
            label = t("ui.skip")
        else:
            label = st.labels[i]
            if st.multi:
                label = ("◉ " if row in st.chosen else "◯ ") + label
        text = cut(("❯ " if cur else "  ") + label, width)
        lines.append(_c("36", text) if cur else text)
    hint = t("ui.keys_multi" if st.multi else "ui.keys_radio")
    if st.custom:
        hint += t("ui.keys_custom")
    lines.append(_c("2", cut(hint, width)))
    if st.message:
        lines.append(_c("31", cut(st.message, width)))
    return lines


def run_menu(io, t: T, title: str, st: MenuState, *, min_selected: int = 0,
             validate: Callable[[list[str]], str | None] | None = None):
    """Draw, read keys, redraw in place; collapse to one summary line at the end."""
    drawn = 0

    def draw():
        nonlocal drawn
        if drawn:
            io.write(f"\x1b[{drawn}F\x1b[J")
        lines = render_menu(st, title, t, max(20, io.columns() - 1))
        io.write("\n".join(lines) + "\n")
        drawn = len(lines)

    def erase():
        if drawn:
            io.write(f"\x1b[{drawn}F\x1b[J")

    draw()
    while True:
        try:
            act = st.handle(io.read_key())
        except KeyboardInterrupt:
            erase()
            raise
        if act is None:
            draw()
            continue
        kind, value = act
        if kind == "cancel":
            erase()
            raise KeyboardInterrupt
        if kind == "custom":
            erase()
            drawn = 0
            txt = " ".join(io.ask(prompt(t("ui.custom_prompt"))).split())
            io.write("\x1b[1F\x1b[J")  # drop the typed line; the menu shows it
            if txt and not st.multi:
                value = txt
                kind = "select"
            else:
                if txt and f"custom:{txt}" not in st.values:
                    st.values.append(f"custom:{txt}")
                    st.labels.append(txt)
                    st.chosen.append(f"custom:{txt}")
                    st.cursor = len(st.values) - 1
                draw()
                continue
        if kind == "confirm":
            if len(value) < min_selected:
                st.message = t("ui.min_selected", n=min_selected)
                draw()
                continue
            err = validate(value) if validate else None
            if err:
                st.message = err
                draw()
                continue
        erase()
        if st.multi:
            answer = "、".join(st.labels[st.values.index(v)] for v in value) or t("ui.skip")
        elif value is None:
            answer = t("ui.skip")
        else:
            answer = st.labels[st.values.index(value)] if value in st.values else value
        io.say(_c("1;36", "? " + title) + " " + _c("36", answer))
        return value


def _menu_capable(io) -> bool:
    fn = getattr(io, "interactive", None)
    return bool(fn and fn() and hasattr(io, "read_key"))


class ScriptedIO:
    """Feeds pre-set answers; records everything shown. EOFError when exhausted."""

    def __init__(self, answers: Sequence[str] = ()):
        self.answers = list(answers)
        self.out: list[str] = []

    def say(self, text: str = "") -> None:
        self.out.append(text)

    def ask(self, prompt: str) -> str:
        self.out.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    @property
    def text(self) -> str:
        return "\n".join(self.out)


def radio(io: IO, t: T, title: str, options: Sequence[tuple[str, str]],
          *, default: str | None = None, allow_custom: bool = False,
          allow_skip: bool = False) -> str | None:
    """options: (value, label). Returns value, custom text, or None for skip."""
    opts = list(options)
    if _menu_capable(io):
        vals = [v for v, _ in opts]
        st = MenuState(values=vals, labels=[lb for _, lb in opts], multi=False,
                       cursor=vals.index(default) if default in vals else 0, chosen=[],
                       custom=allow_custom, skip=allow_skip)
        return run_menu(io, t, title, st)
    while True:
        io.say(question(title))
        for i, (val, label) in enumerate(opts, 1):
            mark = " *" if val == default else ""
            io.say(f"  {i}) {label}{mark}")
        extra = []
        if allow_custom:
            io.say(f"  c) {t('ui.custom')}")
            extra.append("c")
        if allow_skip:
            io.say(f"  s) {t('ui.skip')}")
            extra.append("s")
        ans = io.ask(prompt(t("ui.choose"))).strip()
        if not ans and default is not None:
            return default
        if ans.isdigit() and 1 <= int(ans) <= len(opts):
            return opts[int(ans) - 1][0]
        if allow_custom and ans.lower() == "c":
            txt = io.ask(prompt(t("ui.custom_prompt"))).strip()
            if txt:
                return txt
            continue
        if allow_skip and ans.lower() == "s":
            return None
        io.say(t("ui.invalid"))


def checkbox(io: IO, t: T, title: str, options: Sequence[tuple[str, str]],
             selected: Sequence[str], *, min_selected: int = 0,
             validate: Callable[[list[str]], str | None] | None = None,
             allow_custom: bool = False) -> list[str]:
    """Toggle by number; empty line confirms. Keeps option order in the result.
    With allow_custom, 'c' adds a free-text option, returned as 'custom:<text>'."""
    options = list(options)
    chosen = [v for v, _ in options if v in set(selected)]
    if _menu_capable(io):
        st = MenuState(values=[v for v, _ in options], labels=[lb for _, lb in options],
                       multi=True, cursor=0, chosen=chosen, custom=allow_custom)
        return run_menu(io, t, title, st, min_selected=min_selected, validate=validate)
    while True:
        io.say(question(title))
        for i, (val, label) in enumerate(options, 1):
            box = "[x]" if val in chosen else "[ ]"
            io.say(f"  {i}) {box} {label}")
        ans = io.ask(prompt(t("ui.toggle_custom" if allow_custom else "ui.toggle"))).strip()
        if allow_custom and ans.lower() == "c":
            txt = " ".join(io.ask(prompt(t("ui.custom_prompt"))).split())
            if txt and f"custom:{txt}" not in chosen:
                options.append((f"custom:{txt}", txt))
                chosen.append(f"custom:{txt}")
            continue
        if not ans:
            if len(chosen) < min_selected:
                io.say(t("ui.min_selected", n=min_selected))
                continue
            if validate:
                err = validate(chosen)
                if err:
                    io.say(err)
                    continue
            return chosen
        changed = False
        for tok in ans.replace(",", " ").split():
            if tok.isdigit() and 1 <= int(tok) <= len(options):
                val = options[int(tok) - 1][0]
                if val in chosen:
                    chosen.remove(val)
                else:
                    chosen.append(val)
                changed = True
        if not changed:
            io.say(t("ui.invalid"))
        order = [v for v, _ in options]
        chosen.sort(key=order.index)


def confirm(io: IO, t: T, question: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        ans = io.ask(prompt(f"{question} [{hint}]")).strip().lower()
        if not ans:
            return default
        if ans in ("y", "yes", "是", "好"):
            return True
        if ans in ("n", "no", "否", "不"):
            return False
        io.say(t("ui.invalid"))


def collect_lines(io: IO, t: T, prompt: str, on_entry: Callable[[str], str | None]) -> list[str]:
    """Read entries until '/done', two empty lines in a row, or EOF (Ctrl-D).

    on_entry returns an acknowledgement to echo, or None to reject the entry.
    """
    entries: list[str] = []
    empty_run = 0
    while True:
        try:
            line = io.ask(prompt)
        except EOFError:
            break
        s = line.strip()
        if s in END_TOKENS:
            break
        if not s:
            empty_run += 1
            if empty_run >= 2:
                break
            continue
        empty_run = 0
        ack = on_entry(s)
        if ack is None:
            continue
        entries.append(s)
        io.say(ack)
    return entries


def is_tty() -> bool:
    return sys.stdin.isatty()

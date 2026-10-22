"""Terminal interaction: radio, checkbox, free text, multi-line target entry.

All prompts go through an IO object so tests can script the answers.
"""
from __future__ import annotations

import os
import sys
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

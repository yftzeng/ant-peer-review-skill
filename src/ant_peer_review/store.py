"""Per-user store: config, lessons, site profiles, style guides, runs.

Lives in the platform data directory, never inside the installed package.
"""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .jsonio import write_text_atomic

MODEL_ALIASES = ["opus", "sonnet", "fable"]
DEFAULT_MODELS = ["opus", "sonnet"]
BACKENDS = ["claude-cli", "anthropic-api"]
AVAILABLE_BACKENDS = {"claude-cli"}  # anthropic-api is reserved (D-2 build order)
LANGS = ["en", "zh-TW", "zh-CN"]
MIN_REVIEWERS = 2

PACKAGE_DIR = Path(__file__).resolve().parent


def default_home() -> Path:
    env = os.environ.get("ANT_PEER_REVIEW_HOME")
    if env:
        home = Path(env).expanduser()
    elif sys.platform == "win32":
        home = Path(os.environ.get("APPDATA", Path.home())) / "ant-peer-review"
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        home = Path(base) / "ant-peer-review"
    home = home.resolve()
    if home == PACKAGE_DIR or PACKAGE_DIR in home.parents:
        raise RuntimeError(f"user store must not live inside the installed package: {home}")
    return home


@dataclass
class Config:
    lang: str = "en"
    backend: str = "claude-cli"
    models: list[str] = field(default_factory=lambda: list(DEFAULT_MODELS))
    grade_thresholds: dict[str, float] = field(
        default_factory=lambda: {"excellent": 85.0, "good": 70.0, "revise": 60.0})
    style_guide_min_repeats: int = 3
    configured: bool = False


class Store:
    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home else default_home()

    @property
    def config_path(self) -> Path:
        return self.home / "config.toml"

    @property
    def runs_dir(self) -> Path:
        return self.home / "runs"

    @property
    def lessons_md(self) -> Path:
        return self.home / "LESSONS.md"

    @property
    def lessons_dir(self) -> Path:
        return self.home / "lessons"

    @property
    def site_profiles(self) -> Path:
        return self.home / "site-profiles.json"

    @property
    def style_guides(self) -> Path:
        return self.home / "style-guides"

    @property
    def corrections_log(self) -> Path:
        return self.home / "style-corrections.jsonl"

    def load_config(self) -> Config:
        if not self.config_path.exists():
            return Config()
        data = tomllib.loads(self.config_path.read_text(encoding="utf-8"))
        cfg = Config()
        cfg.lang = data.get("lang", cfg.lang)
        cfg.backend = data.get("backend", cfg.backend)
        cfg.models = [m for m in data.get("models", cfg.models) if m in MODEL_ALIASES]
        cfg.grade_thresholds.update(data.get("grade_thresholds", {}))
        cfg.style_guide_min_repeats = int(data.get("style_guide_min_repeats",
                                                   cfg.style_guide_min_repeats))
        cfg.configured = True
        return cfg

    def save_config(self, cfg: Config) -> None:
        def q(s: str) -> str:
            return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
        lines = [
            "# ant-peer-review user config",
            f"lang = {q(cfg.lang)}",
            f"backend = {q(cfg.backend)}",
            "models = [" + ", ".join(q(m) for m in cfg.models) + "]",
            f"style_guide_min_repeats = {int(cfg.style_guide_min_repeats)}",
            "",
            "[grade_thresholds]",
        ]
        for k, v in cfg.grade_thresholds.items():
            lines.append(f"{k} = {float(v)}")
        write_text_atomic(self.config_path, "\n".join(lines) + "\n")

"""First-use setup and `config` subcommands: language, backend, reviewer models."""
from __future__ import annotations

from .backends.base import Backend
from .i18n import T
from .store import AVAILABLE_BACKENDS, BACKENDS, LANGS, MIN_REVIEWERS, MODEL_ALIASES, Config, Store
from .ui import IO, checkbox, radio

LANG_LABELS = {"en": "English", "zh-TW": "繁體中文", "zh-CN": "简体中文"}


def choose_lang(io: IO, cfg: Config) -> None:
    t = T(cfg.lang)
    cfg.lang = radio(io, t, t("setup.lang"), [(k, LANG_LABELS[k]) for k in LANGS],
                     default=cfg.lang) or cfg.lang


def choose_backend(io: IO, cfg: Config) -> None:
    t = T(cfg.lang)
    while True:
        choice = radio(io, t, t("setup.backend"),
                       [(b, t(f"setup.backend.{b}")) for b in BACKENDS],
                       default=cfg.backend) or cfg.backend
        if choice in AVAILABLE_BACKENDS:
            cfg.backend = choice
            return
        io.say(t("setup.backend_unavailable", backend=choice))


def choose_models(io: IO, cfg: Config, backend: Backend | None) -> list[str]:
    """Checkbox with the saved (or default) models ticked; probes each new pick."""
    t = T(cfg.lang)
    while True:
        picked = checkbox(io, t, t("setup.models"),
                          [(m, m) for m in MODEL_ALIASES], cfg.models,
                          min_selected=MIN_REVIEWERS)
        ok = []
        for m in picked:
            err = backend.probe(m) if backend else None
            if err:
                io.say(t("setup.model_unavailable", model=m, reason=err[:200]))
            else:
                ok.append(m)
        if len(ok) >= MIN_REVIEWERS:
            cfg.models = ok
            return ok
        io.say(t("ui.min_selected", n=MIN_REVIEWERS))


def first_use(io: IO, store: Store, backend_factory) -> Config:
    cfg = store.load_config()
    if cfg.configured:
        return cfg
    io.say(T(cfg.lang)("setup.welcome"))
    choose_lang(io, cfg)
    choose_backend(io, cfg)
    choose_models(io, cfg, backend_factory(cfg.backend))
    store.save_config(cfg)
    io.say(T(cfg.lang)("setup.saved", path=str(store.config_path)))
    cfg.configured = True
    return cfg


def banner(t: T, models: list[str]) -> str:
    return t("run.banner", models=", ".join(models))


def parse_models_override(value: str) -> list[str]:
    models = [m.strip() for m in value.split(",") if m.strip()]
    bad = [m for m in models if m not in MODEL_ALIASES]
    if bad:
        raise ValueError(f"unknown model(s): {', '.join(bad)}; choose from {MODEL_ALIASES}")
    if len(models) < MIN_REVIEWERS:
        raise ValueError(f"at least {MIN_REVIEWERS} reviewers are needed")
    return models


def effective_models(cfg: Config, override: str | None) -> list[str]:
    """The roster for this run: a --models override wins but is never saved."""
    return parse_models_override(override) if override else list(cfg.models)

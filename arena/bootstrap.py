"""Bridge bootstrap helper facade."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from arena.bootstrap_config import get_bridge_port as _get_bridge_port_impl
from arena.bootstrap_config import load_config_file as _load_config_file_impl
from arena.bootstrap_daemon import daemonize as _daemonize_impl
from arena.bootstrap_env import ensure_session_env as _ensure_session_env_impl
from arena.bootstrap_logging import setup_logging as _setup_logging_impl
from arena.bootstrap_token import resolve_token as _resolve_token_impl


def ensure_session_env() -> None:
    return _ensure_session_env_impl()


def load_config_file(
    *,
    log_info: Callable[..., None] | None = None,
    log_debug: Callable[..., None] | None = None,
    log_warning: Callable[..., None] | None = None,
) -> dict:
    return _load_config_file_impl(log_info=log_info, log_debug=log_debug, log_warning=log_warning)


def get_bridge_port() -> int:
    return _get_bridge_port_impl()


def setup_logging(*, app_dir: Path, log_file: Path | None = None) -> logging.Logger:
    return _setup_logging_impl(app_dir=app_dir, log_file=log_file)


def resolve_token(
    cli_token: str | None,
    *,
    default_token_file: Path,
    token_generator: Callable[[], str],
    log_info: Callable[..., None] | None = None,
) -> tuple[str, Path]:
    return _resolve_token_impl(
        cli_token,
        default_token_file=default_token_file,
        token_generator=token_generator,
        log_info=log_info,
    )


def daemonize(*, log_error: Callable[..., None] | None = None) -> None:
    return _daemonize_impl(log_error=log_error)


__all__ = [
    "daemonize",
    "ensure_session_env",
    "get_bridge_port",
    "load_config_file",
    "resolve_token",
    "setup_logging",
]

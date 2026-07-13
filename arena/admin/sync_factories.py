"""Runtime sync factories for admin helper globals."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable


def make_sys_funnel_sync(*, sys_funnel_status_fn: Callable[..., dict[str, Any]], subprocess_kwargs_fn: Callable[[], dict[str, Any]]):
    def _sys_funnel_sync() -> dict[str, Any]:
        return sys_funnel_status_fn(subprocess_kwargs=subprocess_kwargs_fn)

    return _sys_funnel_sync


def make_token_path(*, default_token_file: Path):
    def _token_path() -> Path:
        return Path(os.environ.get("ARENA_TOKEN_FILE", str(default_token_file))).expanduser()

    return _token_path


def make_token_regen_sync(*, token_regenerate_fn: Callable[..., dict[str, Any]], default_token_file: Path):
    def _token_regen_sync(target_path: str = "") -> dict[str, Any]:
        return token_regenerate_fn(target_path, default_token_file=default_token_file)

    return _token_regen_sync


def make_tailscale_funnel_action_sync(*, tailscale_funnel_action_fn: Callable[..., dict[str, Any]]):
    def _tailscale_funnel_action_sync(action: str, port: int) -> dict[str, Any]:
        return tailscale_funnel_action_fn(action, port)

    return _tailscale_funnel_action_sync


def make_zerotier_status_sync(
    *,
    zerotier_status_fn: Callable[..., dict[str, Any]],
    subprocess_kwargs_fn: Callable[[], dict[str, Any]],
):
    def _zerotier_status_sync() -> dict[str, Any]:
        return zerotier_status_fn(subprocess_kwargs=subprocess_kwargs_fn)

    return _zerotier_status_sync


def make_cloudflared_funnel_action_sync(
    *,
    cloudflared_funnel_action_fn: Callable[..., dict[str, Any]],
    root_agent: Path,
    subprocess_kwargs_fn: Callable[[], dict[str, Any]],
):
    def _cloudflared_funnel_action_sync(action: str, port: int) -> dict[str, Any]:
        return cloudflared_funnel_action_fn(
            action,
            port,
            root_agent=root_agent,
            subprocess_kwargs=subprocess_kwargs_fn,
        )

    return _cloudflared_funnel_action_sync

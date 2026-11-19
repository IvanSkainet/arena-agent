"""Shared helpers for API v2 handlers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web

from arena.app_keys import APP_CFG


def cfg_get_max_timeout(request: web.Request) -> int:
    """Get max timeout from bridge config."""
    try:
        return request.app[APP_CFG].get("max_timeout", 600)
    except Exception:
        return 600


def tls_ready(tls_config: dict[str, Any]) -> bool:
    cert_path = tls_config.get("cert_path")
    key_path = tls_config.get("key_path")
    if not tls_config.get("enabled"):
        return False
    if not cert_path or not key_path:
        return False
    return all(Path(path).is_file() for path in (cert_path, key_path))


def auth_and_record(ctx, request: web.Request):
    response = ctx.require_auth(request)
    if response:
        return response
    ctx.record_request()
    return None

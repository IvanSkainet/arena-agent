"""Shared helpers for API v2 handlers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web


def cfg_get_max_timeout(request: web.Request) -> int:
    """Get max timeout from bridge config."""
    try:
        return request.app["cfg"].get("max_timeout", 600)
    except Exception:
        return 600


def tls_ready(tls_config: dict[str, Any]) -> bool:
    cert_path = tls_config.get("cert_path")
    if not cert_path:
        return False
    return bool(tls_config.get("enabled") and Path(cert_path).exists())


def auth_and_record(ctx, request: web.Request):
    response = ctx.require_auth(request)
    if response:
        return response
    ctx.record_request()
    return None

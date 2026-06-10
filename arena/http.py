"""HTTP response helpers shared by bridge handlers."""
from __future__ import annotations

from typing import Any

from aiohttp import web

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Arena-Token, Mcp-Session-Id",
}


def cors_json_response(
    data: Any,
    status: int = 200,
    extra_headers: dict | None = None,
    **kwargs: Any,
) -> web.Response:
    """Return a JSON response with standard bridge CORS headers."""
    headers = dict(CORS_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    return web.json_response(data, status=status, headers=headers, **kwargs)


# Backward-compatible private name used throughout unified_bridge.py.
_cors_json_response = cors_json_response

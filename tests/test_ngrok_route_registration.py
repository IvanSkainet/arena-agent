"""Regression guard for the v4.33.0 -> v4.33.1 ngrok-route bug.

The v4.33.0 live-smoke found that ``/v1/ngrok/tunnel/status``
returned HTTP 404 even though the route was declared in
``arena/route_registry/registry.py`` and the handler was in the
dispatch map. Root cause: routes are actually registered in
``arena/route_registry/core.py`` via ``app.router.add_post`` /
``add_get`` calls -- the registry.py data was correct but never
consulted for the ``add_*`` calls.

This test asserts that ``core.py`` adds both the POST and the
GET route for ``/v1/ngrok/tunnel/{action}``. Missing either one
would silently drop the route and 404 users again.
"""
from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_CORE = _REPO / "arena" / "route_registry" / "core.py"


def test_core_registers_post_and_get_for_ngrok_tunnel():
    src = _CORE.read_text(encoding="utf-8")
    assert 'add_post("/v1/ngrok/tunnel/{action}"' in src, (
        "route_registry/core.py missing add_post for "
        "/v1/ngrok/tunnel/{action} -- would return 404 at runtime "
        "even though registry.py declares it."
    )
    assert 'add_get("/v1/ngrok/tunnel/{action}"' in src, (
        "route_registry/core.py missing add_get for "
        "/v1/ngrok/tunnel/{action}."
    )


def test_core_uses_handle_v1_ngrok_tunnel_handler():
    """Both registrations must dispatch to the correct handler
    name -- a typo here would map to a NameError at boot."""
    src = _CORE.read_text(encoding="utf-8")
    assert 'h["handle_v1_ngrok_tunnel"]' in src


def test_core_registers_ngrok_alongside_cloudflared():
    """Same file registers both -- if a future refactor moves
    the cloudflared routes elsewhere, the ngrok routes should
    follow to stay siblings visually and functionally."""
    src = _CORE.read_text(encoding="utf-8")
    cf_idx = src.find('/v1/cloudflared/tunnel/{action}')
    ng_idx = src.find('/v1/ngrok/tunnel/{action}')
    assert cf_idx >= 0 and ng_idx >= 0
    # ngrok should be within 500 chars of cloudflared -- close
    # enough that a code reviewer will notice if one moves without
    # the other.
    assert abs(ng_idx - cf_idx) < 500

"""Regression guard for the v4.47.0 bore-route wiring.

The v4.33.0 -> v4.33.1 ngrok live-smoke found that route data
in ``arena/route_registry/registry.py`` alone was not enough --
the actual ``app.router.add_*`` calls live in
``arena/route_registry/core.py``. This test locks in the same
"both places must agree" invariant for the new bore endpoints
so a future refactor cannot silently 404 ``/v1/bore/tunnel/*``.
"""
from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_CORE = _REPO / "arena" / "route_registry" / "core.py"
_REGISTRY = _REPO / "arena" / "route_registry" / "registry.py"


def test_core_registers_post_and_get_for_bore_tunnel():
    src = _CORE.read_text(encoding="utf-8")
    assert 'add_post("/v1/bore/tunnel/{action}"' in src, (
        "route_registry/core.py missing add_post for "
        "/v1/bore/tunnel/{action} -- would return 404 at runtime "
        "even though registry.py declares it."
    )
    assert 'add_get("/v1/bore/tunnel/{action}"' in src, (
        "route_registry/core.py missing add_get for "
        "/v1/bore/tunnel/{action}."
    )


def test_core_uses_handle_v1_bore_tunnel_handler():
    """Both registrations must dispatch to the correct handler
    name -- a typo here would map to a NameError at boot."""
    src = _CORE.read_text(encoding="utf-8")
    assert 'h["handle_v1_bore_tunnel"]' in src


def test_registry_declares_bore_routes():
    """The declarative route table must also list bore -- some
    diagnostic tooling reads registry.py directly (e.g. the
    dashboard's route inventory)."""
    src = _REGISTRY.read_text(encoding="utf-8")
    assert '/v1/bore/tunnel/{action}' in src
    assert 'handle_v1_bore_tunnel' in src


def test_core_registers_bore_alongside_ngrok():
    """Same file registers both -- if a future refactor moves
    the ngrok routes elsewhere, the bore routes should follow
    to stay siblings visually and functionally."""
    src = _CORE.read_text(encoding="utf-8")
    ng_idx = src.find("/v1/ngrok/tunnel/{action}")
    br_idx = src.find("/v1/bore/tunnel/{action}")
    assert ng_idx >= 0 and br_idx >= 0
    # bore should be within 500 chars of ngrok -- close enough
    # that a code reviewer will notice if one moves without
    # the other.
    assert abs(br_idx - ng_idx) < 500

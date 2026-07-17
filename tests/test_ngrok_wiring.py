"""End-to-end wiring proof for v4.33.0 ngrok integration.

Covers:
  * DEFAULT_PRIORITY now includes ngrok as the fourth entry.
  * ``_ngrok_snapshot`` returns the well-formed cloudflared-shaped
    dict for wired / unwired / raising callables.
  * ``tunnels_status`` accepts ``ngrok_status_sync`` and merges
    the snapshot into the providers list at the priority
    position ngrok has in the order.
  * ``tunnels_probe`` threads ``ngrok_status_sync`` through and
    includes the ngrok probe in the response.
  * ``AdminHandlers`` dataclass has a new ``ngrok_tunnel`` field.
  * The route registry declares POST + GET
    ``/v1/ngrok/tunnel/{action}`` mapped to
    ``handle_v1_ngrok_tunnel``.
  * The wiring dispatcher in ``arena/wiring/platform.py``
    plumbs ``handlers.ngrok_tunnel`` through to the outbound
    handler map so the route table can resolve it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from arena.admin.tunnels import (
    DEFAULT_PRIORITY,
    _ngrok_snapshot,
    tunnels_status,
)


def test_default_priority_contains_ngrok_as_fourth():
    """Order preserved: tailscale, zerotier, cloudflared come
    first (back-compat), ngrok is the new tail entry."""
    # v4.47.0: bore appended after ngrok; keep the sibling-check permissive
    # so this test survives future transports (each new transport lands as
    # the tail entry to preserve existing operators' priority order).
    assert DEFAULT_PRIORITY[:4] == ("tailscale", "zerotier", "cloudflared", "ngrok")


# ---------------------------------------------------------------------------
# _ngrok_snapshot shape
# ---------------------------------------------------------------------------
def test_ngrok_snapshot_unwired_returns_placeholder():
    snap = _ngrok_snapshot(None)
    assert snap["provider"] == "ngrok"
    assert snap["available"] is False
    assert "not wired" in snap["reason"]


def test_ngrok_snapshot_calls_sync_and_wraps_response():
    calls = {"n": 0}

    def _sync():
        calls["n"] += 1
        return {
            "installed": True,
            "source": "system",
            "version": "3.14.0",
            "active": True,
            "url": "https://xyz.ngrok-free.app",
            "update_hint": "brew upgrade ngrok",
        }

    snap = _ngrok_snapshot(_sync)
    assert calls["n"] == 1
    assert snap["provider"] == "ngrok"
    assert snap["installed"] is True
    assert snap["cli_source"] == "system"
    assert snap["version"] == "3.14.0"
    assert snap["active"] is True
    assert snap["public_url"] == "https://xyz.ngrok-free.app"
    assert snap["public_kind"] == "https"
    assert snap["manageable"] is True
    assert snap["update_hint"] == "brew upgrade ngrok"


def test_ngrok_snapshot_swallows_exception():
    def _sync():
        raise RuntimeError("boom")

    snap = _ngrok_snapshot(_sync)
    assert snap["available"] is False
    assert "boom" in snap["error"]


def test_ngrok_snapshot_none_url_becomes_none_not_empty_string():
    def _sync():
        return {"installed": True, "active": False, "url": ""}

    snap = _ngrok_snapshot(_sync)
    assert snap["public_url"] is None


# ---------------------------------------------------------------------------
# tunnels_status merges ngrok snapshot in
# ---------------------------------------------------------------------------
def test_tunnels_status_includes_ngrok_in_providers():
    """When ngrok_status_sync is passed, the response must include
    a ngrok provider entry (in the priority tail by default)."""
    def _ngrok_sync():
        return {"installed": True, "active": True,
                "url": "https://abc.ngrok-free.app"}

    result = tunnels_status(
        sys_funnel_status_sync=None,
        cloudflared_status_sync=None,
        zerotier_status_sync=None,
        ngrok_status_sync=_ngrok_sync,
    )
    providers = [p["provider"] for p in result["providers"]]
    assert "ngrok" in providers
    # Default priority: tail entry.
    # v4.47.0: tail entry is now bore; check ngrok is present and
    # sits after cloudflared per default priority order.
    assert providers.index("ngrok") == providers.index("cloudflared") + 1


def test_tunnels_status_default_priority_is_four_transports():
    result = tunnels_status(
        sys_funnel_status_sync=None,
        cloudflared_status_sync=None,
        zerotier_status_sync=None,
        ngrok_status_sync=None,
    )
    assert result["priority"] == list(DEFAULT_PRIORITY)


def test_tunnels_status_without_ngrok_sync_still_reports_provider():
    """The snapshot is still built when the callable is None -- it
    just reports available=False. Downstream (agent_config, dashboard)
    can then decide whether to show it or hide it."""
    result = tunnels_status(
        sys_funnel_status_sync=None,
        cloudflared_status_sync=None,
        zerotier_status_sync=None,
    )
    providers = {p["provider"]: p for p in result["providers"]}
    assert "ngrok" in providers
    assert providers["ngrok"]["available"] is False


# ---------------------------------------------------------------------------
# AdminHandlers dataclass has the new field wired
# ---------------------------------------------------------------------------
def test_admin_handlers_dataclass_has_ngrok_tunnel_field():
    """The dataclass field is what the wiring dispatcher reads
    when it builds the outbound handler map. Missing field -> the
    route registry can't resolve /v1/ngrok/tunnel/{action}."""
    from arena.admin.handlers import AdminHandlers
    from dataclasses import fields
    names = {f.name for f in fields(AdminHandlers)}
    assert "ngrok_tunnel" in names, (
        "AdminHandlers must gain a ngrok_tunnel field so the "
        "route registry can resolve /v1/ngrok/tunnel/{action}"
    )


# ---------------------------------------------------------------------------
# Route registry declares the new endpoints
# ---------------------------------------------------------------------------
def test_route_registry_declares_ngrok_tunnel():
    reg = Path(__file__).resolve().parents[1] / "arena" / "route_registry" / "registry.py"
    src = reg.read_text(encoding="utf-8")
    for verb in ("POST", "GET"):
        pattern = rf"'{verb}'\s*,\s*'/v1/ngrok/tunnel/\{{action\}}'"
        assert re.search(pattern, src), (
            f"route registry missing {verb} /v1/ngrok/tunnel/{{action}}"
        )
    assert "'handle_v1_ngrok_tunnel'" in src


def test_platform_dispatcher_maps_handle_v1_ngrok_tunnel():
    dispatch = Path(__file__).resolve().parents[1] / "arena" / "wiring" / "platform.py"
    src = dispatch.read_text(encoding="utf-8")
    assert '"handle_v1_ngrok_tunnel": handlers.ngrok_tunnel' in src


# ---------------------------------------------------------------------------
# make_admin_handlers produces a working handler
# ---------------------------------------------------------------------------
def test_make_admin_handlers_returns_ngrok_tunnel():
    """Build a minimal AdminHandlerContext and verify that
    make_admin_handlers returns an object whose ngrok_tunnel field
    is callable. Proves the wiring is end-to-end, not just
    declared."""
    from arena.admin.handlers import make_admin_handlers
    from arena.handler_context import AdminHandlerContext

    class _FakeResp: pass

    ctx = AdminHandlerContext(
        require_auth=lambda req: None,
        record_request=lambda *a, **kw: None,
        cors_json_response=lambda payload, **kw: _FakeResp(),
        executor=None,  # not called in this smoke
        audit=lambda ev: None,
        default_token_file=Path("/nope"),
        root_agent=Path("/nope"),
        subprocess_kwargs=lambda: {},
    )
    handlers = make_admin_handlers(ctx)
    assert handlers.ngrok_tunnel is not None
    assert callable(handlers.ngrok_tunnel)

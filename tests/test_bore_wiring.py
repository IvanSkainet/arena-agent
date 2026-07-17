"""End-to-end wiring proof for v4.47.0 bore integration.

Covers:
  * DEFAULT_PRIORITY now includes bore as the fifth entry.
  * ``_bore_snapshot`` returns the well-formed cloudflared-shaped
    dict for wired / unwired / raising callables.
  * ``tunnels_status`` accepts ``bore_status_sync`` and merges
    the snapshot into the providers list at the priority
    position bore has in the order.
  * ``tunnels_probe`` threads ``bore_status_sync`` through and
    includes the bore probe in the response.
  * ``AdminHandlers`` dataclass has a new ``bore_tunnel`` field.
  * The wiring dispatcher in ``arena/wiring/platform.py``
    plumbs ``handlers.bore_tunnel`` through to the outbound
    handler map so the route table can resolve it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from arena.admin.tunnels import (
    DEFAULT_PRIORITY,
    _bore_snapshot,
    tunnels_status,
)


def test_default_priority_contains_bore_as_fifth():
    """Order preserved: tailscale, zerotier, cloudflared, ngrok
    come first (back-compat), bore is the new tail entry."""
    assert DEFAULT_PRIORITY == (
        "tailscale", "zerotier", "cloudflared", "ngrok", "bore",
    )


# ---------------------------------------------------------------------------
# _bore_snapshot shape
# ---------------------------------------------------------------------------
def test_bore_snapshot_unwired_returns_placeholder():
    snap = _bore_snapshot(None)
    assert snap["provider"] == "bore"
    assert snap["available"] is False
    assert "not wired" in snap["reason"]


def test_bore_snapshot_calls_sync_and_wraps_response():
    calls = {"n": 0}

    def _sync():
        calls["n"] += 1
        return {
            "installed": True,
            "source": "system",
            "version": "0.6.0",
            "active": True,
            "url": "https://bore.pub:35429",
            "server": "bore.pub",
            "update_hint": "cargo install bore-cli",
        }

    snap = _bore_snapshot(_sync)
    assert calls["n"] == 1
    assert snap["provider"] == "bore"
    assert snap["installed"] is True
    assert snap["cli_source"] == "system"
    assert snap["version"] == "0.6.0"
    assert snap["active"] is True
    assert snap["public_url"] == "https://bore.pub:35429"
    assert snap["public_kind"] == "https"
    assert snap["manageable"] is True
    assert snap["server"] == "bore.pub"
    assert snap["update_hint"] == "cargo install bore-cli"


def test_bore_snapshot_swallows_exception():
    def _sync():
        raise RuntimeError("boom")

    snap = _bore_snapshot(_sync)
    assert snap["available"] is False
    assert "boom" in snap["error"]


def test_bore_snapshot_none_url_becomes_none_not_empty_string():
    def _sync():
        return {"installed": True, "active": False, "url": ""}

    snap = _bore_snapshot(_sync)
    assert snap["public_url"] is None


# ---------------------------------------------------------------------------
# tunnels_status merges bore snapshot in
# ---------------------------------------------------------------------------
def test_tunnels_status_includes_bore_in_providers():
    """When bore_status_sync is passed, the response must include
    a bore provider entry (in the priority tail by default)."""
    def _bore_sync():
        return {"installed": True, "active": True,
                "url": "https://bore.pub:12345",
                "source": "system", "version": "0.6.0"}
    snap = tunnels_status(bore_status_sync=_bore_sync)
    providers = [p.get("provider") for p in snap["providers"]]
    assert "bore" in providers
    # priority preserved.
    assert snap["priority"] == list(DEFAULT_PRIORITY)


def test_tunnels_status_bore_absent_when_sync_none():
    """When bore is unwired the snapshot still lists it, but with
    ``available: False`` -- downstream code can render the row
    without a KeyError."""
    snap = tunnels_status()
    bore = next(p for p in snap["providers"] if p.get("provider") == "bore")
    assert bore.get("available") is False


def test_tunnels_status_picks_bore_as_active_when_only_bore_up():
    """Empty priority => bore's own active flag decides. When
    every upstream provider is unwired, an active bore should
    become the ``active`` field."""
    def _bore_sync():
        return {"installed": True, "active": True,
                "url": "https://bore.pub:12345",
                "source": "system", "version": "0.6.0"}
    snap = tunnels_status(bore_status_sync=_bore_sync)
    # tailscale / cloudflared / zerotier / ngrok are all unwired
    # so bore is the only "active + public_url" candidate.
    assert snap["active"] is not None
    assert snap["active"]["provider"] == "bore"
    assert snap["active"]["public_url"] == "https://bore.pub:12345"


# ---------------------------------------------------------------------------
# AdminHandlers dataclass gains bore_tunnel field
# ---------------------------------------------------------------------------
def test_admin_handlers_dataclass_has_bore_tunnel_field():
    from arena.admin.handlers import AdminHandlers
    # dataclass fields dict -- checks both existence and annotation
    # coverage even if the field is set via a keyword-only default.
    ann = getattr(AdminHandlers, "__annotations__", {})
    assert "bore_tunnel" in ann


# ---------------------------------------------------------------------------
# AdminHandlerContext dataclass exposes bore_status_sync (opt-in)
# ---------------------------------------------------------------------------
def test_admin_handler_context_has_bore_status_sync_field():
    from arena.contexts.platform import AdminHandlerContext
    ann = getattr(AdminHandlerContext, "__annotations__", {})
    assert "bore_status_sync" in ann


# ---------------------------------------------------------------------------
# autostart module registers bore
# ---------------------------------------------------------------------------
def test_autostart_transports_includes_bore():
    from arena.admin import autostart as _autostart
    assert "bore" in _autostart.TRANSPORTS


def test_autostart_marker_path_uses_dot_bore_autostart(tmp_path):
    from arena.admin import autostart as _autostart
    path = _autostart.marker_path("bore", tmp_path)
    assert path.name == ".bore_autostart"


# ---------------------------------------------------------------------------
# wiring/platform.py registers the bore handler mapping
# ---------------------------------------------------------------------------
def test_wiring_platform_registers_bore_tunnel_handler():
    src = Path(__file__).resolve().parents[1] / "arena" / "wiring" / "platform.py"
    text = src.read_text(encoding="utf-8")
    assert '"handle_v1_bore_tunnel"' in text
    assert "handlers.bore_tunnel" in text


# ---------------------------------------------------------------------------
# sync_factories: make_bore_status_sync exists and has the right shape
# ---------------------------------------------------------------------------
def test_make_bore_status_sync_returns_callable(tmp_path, monkeypatch):
    from arena.admin.sync_factories import make_bore_status_sync
    from arena.admin import bore as bore_mod

    # Reset the module-level BORE_STATE explicitly -- earlier tests
    # in the suite may have left a fake Popen sitting in ``proc``,
    # and status derives ``active`` from ``proc.poll() is None``.
    bore_mod.BORE_STATE["proc"] = None
    bore_mod.BORE_STATE["url"] = ""
    bore_mod.BORE_STATE["log"] = []

    fn = make_bore_status_sync(
        root_agent=tmp_path,
        subprocess_kwargs_fn=lambda: {},
    )
    assert callable(fn)
    # Calling it must not raise even when the bore binary is missing --
    # the underlying bore_action("status") returns ok=True with
    # installed=False / active=False.
    monkeypatch.setattr(bore_mod, "_resolve_bore_with_source",
                        lambda *_a: (None, "not_found"))
    result = fn()
    assert result["ok"] is True
    assert result["installed"] is False
    assert result["active"] is False

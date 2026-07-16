"""Tunnels facade regressions.

These tests never touch the network — provider callables are stubbed.
Ensures the priority/failover contract is correct on every OS.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.admin.tunnels import (
    DEFAULT_PRIORITY,
    _priority_from_env,
    tunnels_active,
    tunnels_start,
    tunnels_status,
    tunnels_stop,
)


# ---------------------------------------------------------------------------
# Provider stubs
# ---------------------------------------------------------------------------
def _stub_ts_ok():
    return {
        "ok": True,
        "tailscale": {"installed": True, "connected": True},
        "funnel": {"active": True, "url": "https://alice.tail.example.ts.net"},
    }


def _stub_ts_off():
    return {
        "ok": True,
        "tailscale": {"installed": True, "connected": False},
        "funnel": {"active": False, "url": ""},
    }


def _stub_cf_ok():
    return {
        "ok": True, "installed": True, "source": "system", "version": "2026.7.1",
        "active": True, "url": "https://foo.trycloudflare.com",
    }


def _stub_cf_off():
    return {
        "ok": True, "installed": True, "source": "system", "version": "2026.7.1",
        "active": False, "url": "",
    }


def _stub_zt_ok():
    return {
        "ok": True, "installed": True, "backend": "http", "cli_source": None,
        "platform": "linux",
        "zerotier": {"node_id": "aaaa", "version": "1.16", "connected": True, "online": True},
        "networks": [{"nwid": "nw1", "active": True, "assignedAddresses": ["10.0.0.5/24"]}],
        "active_count": 1,
    }


def _stub_zt_off():
    return {"ok": False, "installed": False, "backend": "none",
            "platform": "linux", "zerotier": {}, "networks": [], "active_count": 0}


# ---------------------------------------------------------------------------
def test_default_priority_order():
    """v4.1.0: ZeroTier is now second (ahead of cloudflared) because
    cloudflared quick-tunnels routinely drop on flaky ISP links. The
    stable overlay is preferred as long as Tailscale isn't available.

    v4.33.0: ngrok added as the fourth entry so existing operators
    see the same primary/secondary order they had before. Override
    with ARENA_TUNNEL_PRIORITY to reorder."""
    assert DEFAULT_PRIORITY == ("tailscale", "zerotier", "cloudflared", "ngrok")


def test_priority_env_override(monkeypatch):
    monkeypatch.setenv("ARENA_TUNNEL_PRIORITY", "cloudflared,zerotier")
    order = _priority_from_env()
    # First two respected, tailscale appended (never dropped).
    assert order[0] == "cloudflared"
    assert order[1] == "zerotier"
    assert "tailscale" in order


def test_priority_env_ignores_unknown(monkeypatch):
    monkeypatch.setenv("ARENA_TUNNEL_PRIORITY", "unknown,zerotier")
    order = _priority_from_env()
    assert "unknown" not in order
    assert order[0] == "zerotier"


def test_status_contract_shape():
    snap = tunnels_status(
        sys_funnel_status_sync=_stub_ts_off,
        cloudflared_status_sync=_stub_cf_off,
        zerotier_status_sync=_stub_zt_off,
    )
    assert snap["ok"] is True
    assert snap["priority"] == list(DEFAULT_PRIORITY)
    providers = {p["provider"] for p in snap["providers"]}
    # v4.33.0: ngrok joined as the fourth transport. Preserving
    # the invariant that every provider in DEFAULT_PRIORITY shows
    # up in the snapshot (even when unwired -- it reports
    # available:false).
    assert providers == {"tailscale", "cloudflared", "zerotier", "ngrok"}
    assert snap["active"] is None  # nothing running


def test_status_picks_highest_priority_active():
    snap = tunnels_status(
        sys_funnel_status_sync=_stub_ts_ok,
        cloudflared_status_sync=_stub_cf_ok,
        zerotier_status_sync=_stub_zt_ok,
    )
    assert snap["active"]["provider"] == "tailscale"
    assert snap["active"]["public_url"].startswith("https://alice.tail")


def test_status_failover_to_next():
    """v4.1.0: when Tailscale is down but ZeroTier is up, ZeroTier
    wins (it's second in the default priority ahead of cloudflared)."""
    snap = tunnels_status(
        sys_funnel_status_sync=_stub_ts_off,
        cloudflared_status_sync=_stub_cf_ok,
        zerotier_status_sync=_stub_zt_ok,
    )
    assert snap["active"]["provider"] == "zerotier"


def test_status_failover_to_cloudflared_when_zerotier_absent():
    """When Tailscale AND ZeroTier are down, cloudflared is the
    fallback of last resort (it's still in the default priority)."""
    snap = tunnels_status(
        sys_funnel_status_sync=_stub_ts_off,
        cloudflared_status_sync=_stub_cf_ok,
        zerotier_status_sync=_stub_zt_off,
    )
    assert snap["active"]["provider"] == "cloudflared"


def test_status_failover_to_zerotier():
    """When tailscale + cloudflared down, ZeroTier lan IP is offered."""
    snap = tunnels_status(
        sys_funnel_status_sync=_stub_ts_off,
        cloudflared_status_sync=_stub_cf_off,
        zerotier_status_sync=_stub_zt_ok,
    )
    assert snap["active"]["provider"] == "zerotier"
    assert snap["active"]["public_url"] == "http://10.0.0.5:8765"


def test_active_endpoint_only():
    active = tunnels_active(
        sys_funnel_status_sync=_stub_ts_ok,
        cloudflared_status_sync=_stub_cf_off,
        zerotier_status_sync=_stub_zt_off,
    )
    assert active["ok"] is True
    assert active["active"]["provider"] == "tailscale"


def test_priority_override_changes_active(monkeypatch):
    """Custom priority actually flips which provider wins."""
    monkeypatch.setenv("ARENA_TUNNEL_PRIORITY", "cloudflared,tailscale,zerotier")
    snap = tunnels_status(
        sys_funnel_status_sync=_stub_ts_ok,
        cloudflared_status_sync=_stub_cf_ok,
        zerotier_status_sync=_stub_zt_ok,
    )
    assert snap["active"]["provider"] == "cloudflared"


def test_start_stops_at_first_healthy():
    calls = []

    def ts_action(action, port):
        calls.append(("ts", action, port))
        return {"ok": True, "action": action}

    def cf_action(action, port):
        calls.append(("cf", action, port))
        return {"ok": True, "action": action}

    result = tunnels_start(
        port=8765,
        tailscale_funnel_action_sync=ts_action,
        cloudflared_funnel_action_sync=cf_action,
        sys_funnel_status_sync=_stub_ts_ok,  # tailscale healthy immediately
        cloudflared_status_sync=_stub_cf_off,
        zerotier_status_sync=_stub_zt_off,
    )
    assert result["ok"] is True
    assert result["active"]["provider"] == "tailscale"
    # cloudflared was never asked because tailscale went healthy first.
    assert not any(c[0] == "cf" for c in calls)


def test_start_continues_if_first_fails():
    """When tailscale can't come up, cloudflared start is attempted."""
    calls = []

    def ts_action(action, port):
        calls.append(("ts", action, port))
        return {"ok": False, "error": "no tailnet"}

    def cf_action(action, port):
        calls.append(("cf", action, port))
        return {"ok": True, "action": action}

    result = tunnels_start(
        port=8765,
        tailscale_funnel_action_sync=ts_action,
        cloudflared_funnel_action_sync=cf_action,
        sys_funnel_status_sync=_stub_ts_off,
        cloudflared_status_sync=_stub_cf_ok,   # cloudflared reports healthy after start
        zerotier_status_sync=_stub_zt_off,
    )
    assert result["ok"] is True
    assert result["active"]["provider"] == "cloudflared"
    # both were called
    assert any(c[0] == "ts" for c in calls)
    assert any(c[0] == "cf" for c in calls)


def test_stop_calls_both():
    calls = []
    tunnels_stop(
        port=8765,
        tailscale_funnel_action_sync=lambda a, p: (calls.append(("ts", a)), {"ok": True})[1],
        cloudflared_funnel_action_sync=lambda a, p: (calls.append(("cf", a)), {"ok": True})[1],
    )
    assert ("ts", "stop") in calls
    assert ("cf", "stop") in calls


def test_zerotier_start_is_noop():
    """We deliberately do not toggle ZeroTier membership on tunnels_start."""
    result = tunnels_start(
        port=8765,
        tailscale_funnel_action_sync=None,
        cloudflared_funnel_action_sync=None,
        sys_funnel_status_sync=_stub_ts_off,
        cloudflared_status_sync=_stub_cf_off,
        zerotier_status_sync=_stub_zt_off,
    )
    zerotier_entry = [e for e in result["log"] if e["provider"] == "zerotier"][0]
    assert zerotier_entry["action"] == "noop"


def test_provider_callable_exceptions_do_not_crash_status():
    def boom():
        raise RuntimeError("simulated failure")

    snap = tunnels_status(
        sys_funnel_status_sync=boom,
        cloudflared_status_sync=_stub_cf_off,
        zerotier_status_sync=_stub_zt_off,
    )
    ts = [p for p in snap["providers"] if p["provider"] == "tailscale"][0]
    assert "simulated failure" in ts.get("error", "")


def test_tailscale_installed_inferred_from_status_string():
    """sys_funnel_status doesn't always emit 'installed', so infer it from state."""
    def ts_status_only():
        return {
            "ok": True,
            "tailscale": {"connected": True, "status": "100.66.158.48   host  user@  linux  -"},
            "funnel": {"active": True, "url": "https://host.example.ts.net"},
        }

    snap = tunnels_status(
        sys_funnel_status_sync=ts_status_only,
        cloudflared_status_sync=_stub_cf_off,
        zerotier_status_sync=_stub_zt_off,
    )
    ts = [p for p in snap["providers"] if p["provider"] == "tailscale"][0]
    assert ts["installed"] is True, "installed must be inferred even without explicit flag"
    assert ts["active"] is True
    assert ts["public_url"] == "https://host.example.ts.net"


def test_tailscale_installed_false_when_no_state():
    """If sys_funnel_status returns empty, tailscale is genuinely not present."""
    def ts_empty():
        return {"ok": True, "tailscale": {}, "funnel": {}}

    snap = tunnels_status(
        sys_funnel_status_sync=ts_empty,
        cloudflared_status_sync=_stub_cf_off,
        zerotier_status_sync=_stub_zt_off,
    )
    ts = [p for p in snap["providers"] if p["provider"] == "tailscale"][0]
    assert ts["installed"] is False
    assert ts["active"] is False

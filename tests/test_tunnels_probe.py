"""Tests for tunnels_probe + v4.1.0 ZeroTier-as-transport priority."""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.admin.tunnels import (
    DEFAULT_PRIORITY,
    _parse_url_host_port,
    _priority_from_env,
    _probe_tcp,
    _zerotier_snapshot,
    tunnels_probe,
    tunnels_status,
)


# --- v4.1.0 priority: ZeroTier ahead of cloudflared ------------------

def test_default_priority_puts_zerotier_ahead_of_cloudflared():
    """v4.1.0: cloudflared quick-tunnels are the most brittle transport
    in practice (silent disconnects); ZeroTier's stable overlay should
    outrank it in the default order so agents get the reliable path first.

    v4.33.0: ngrok added as the fourth transport (tail). The zerotier-
    ahead-of-cloudflared invariant this test guards is unaffected.
    """
    assert DEFAULT_PRIORITY == ("tailscale", "zerotier", "cloudflared", "ngrok", "bore")


def test_env_override_preserves_all_providers(monkeypatch):
    monkeypatch.setenv("ARENA_TUNNEL_PRIORITY", "zerotier,tailscale")
    order = _priority_from_env()
    # User order preserved, missing providers appended in DEFAULT order.
    assert order[0] == "zerotier"
    assert order[1] == "tailscale"
    assert "cloudflared" in order


# --- URL parsing --------------------------------------------------------

def test_parse_url_host_port_plain_http():
    host, port = _parse_url_host_port("http://100.66.158.48:8765/health")
    assert host == "100.66.158.48"
    assert port == 8765


def test_parse_url_host_port_https_no_explicit_port():
    host, port = _parse_url_host_port("https://cachyos-x8664.ts.net/health",
                                     default_port=8765)
    assert host == "cachyos-x8664.ts.net"
    # HTTPS default 443 comes from urlparse, not our fallback.
    assert port == 443


def test_parse_url_host_port_ipv6():
    host, port = _parse_url_host_port("http://[fd00::1]:8765/")
    assert host == "fd00::1"
    assert port == 8765


def test_parse_url_host_port_malformed_returns_default():
    host, port = _parse_url_host_port("not-a-url", default_port=8765)
    assert host in ("not-a-url", "")   # urlparse is lenient about bare strings
    assert port == 8765


# --- TCP probe against a real ephemeral local server -----------------

def _tiny_tcp_server(port_slot: list[int], ready: threading.Event, stop: threading.Event):
    """Bind to an ephemeral port, accept connections until stopped.
    Signals ``ready`` once the port is bound so callers can dial in
    without polling — this eliminates a race where CI runners under
    load would probe before the server had actually bound."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    srv.settimeout(0.5)  # short poll so `stop` is observed promptly
    port_slot.append(srv.getsockname()[1])
    ready.set()
    while not stop.is_set():
        try:
            conn, _ = srv.accept()
            conn.close()
        except socket.timeout:
            continue
        except Exception:
            break
    srv.close()


def test_probe_tcp_success():
    port_slot: list[int] = []
    ready = threading.Event()
    stop = threading.Event()
    t = threading.Thread(target=_tiny_tcp_server, args=(port_slot, ready, stop))
    t.start()
    try:
        # Block until the server signalled ready (or 5s of CI slack).
        assert ready.wait(timeout=5.0), "test server never signalled ready"
        assert port_slot, "test server bound but port slot empty"
        # 3s timeout on the probe itself — CI runners can be slow.
        result = _probe_tcp("127.0.0.1", port_slot[0], timeout=3.0)
        assert result["ok"] is True, f"probe failed: {result}"
        assert result["duration_ms"] >= 0
        assert "error" not in result
    finally:
        stop.set()
        t.join(timeout=3)


def test_probe_tcp_refused():
    # High port unlikely to be listening on any dev machine.
    result = _probe_tcp("127.0.0.1", 1, timeout=0.5)
    assert result["ok"] is False
    assert result.get("error")


def test_probe_tcp_timeout_short():
    """Non-routable RFC 5737 doc IP: connect will hang until timeout."""
    result = _probe_tcp("192.0.2.1", 65432, timeout=0.3)
    assert result["ok"] is False
    assert "timeout" in (result.get("error") or "").lower() or result["duration_ms"] >= 300


# --- ZeroTier snapshot builds ready-to-dial URLs --------------------

def test_zerotier_snapshot_builds_ipv4_url():
    def _stub():
        return {
            "installed": True,
            "backend": "cli",
            "zerotier": {"node_id": "aabbccddee", "connected": True, "online": True},
            "networks": [
                {"id": "0123456789abcdef",
                 "active": True,
                 "assignedAddresses": ["10.147.17.5/24", "fd80::1/128"]},
            ],
        }
    snap = _zerotier_snapshot(_stub, port=8765)
    assert snap["active"] is True
    assert snap["public_url"] == "http://10.147.17.5:8765"
    assert snap["assigned_ipv4"] == ["10.147.17.5"]
    assert snap["assigned_ipv6"] == ["fd80::1"]
    # Both URLs available for callers that want IPv6 explicitly.
    assert "http://10.147.17.5:8765" in snap["public_urls"]
    assert "http://[fd80::1]:8765" in snap["public_urls"]


def test_zerotier_snapshot_no_active_networks():
    def _stub():
        return {
            "installed": True,
            "backend": "cli",
            "zerotier": {"connected": False},
            "networks": [],
        }
    snap = _zerotier_snapshot(_stub, port=8765)
    assert snap["active"] is False
    assert snap["public_url"] is None
    assert snap["public_urls"] == []


# --- tunnels_probe -----------------------------------------------------

def test_tunnels_probe_shape():
    """No providers wired: probe returns an ok:True response with an
    empty probes list rather than crashing."""
    result = tunnels_probe()
    assert result["ok"] is True
    assert "probes" in result
    assert "priority" in result
    assert isinstance(result["reachable_count"], int)


def test_tunnels_probe_zerotier_dial_local_server(monkeypatch):
    """When ZeroTier snapshot exposes a reachable http:// URL, the
    probe should confirm it. Uses a local ephemeral server + a fake
    ZeroTier snapshot pointing at it, so no ZT install needed."""
    port_slot: list[int] = []
    ready = threading.Event()
    stop = threading.Event()
    t = threading.Thread(target=_tiny_tcp_server, args=(port_slot, ready, stop))
    t.start()
    try:
        assert ready.wait(timeout=5.0), "test server never signalled ready"
        listening_port = port_slot[0]

        def fake_zt_status():
            return {
                "installed": True,
                "backend": "cli",
                "zerotier": {"node_id": "aabbccddee", "connected": True, "online": True},
                "networks": [{"id": "0123456789abcdef", "active": True,
                              "assignedAddresses": ["127.0.0.1/32"]}],
            }

        # 3s per-probe timeout gives CI plenty of head-room on slow
        # runners; localhost connect normally completes in <10ms.
        result = tunnels_probe(
            zerotier_status_sync=fake_zt_status,
            port=listening_port,
            timeout=3.0,
            priority=("zerotier",),
        )
        assert result["ok"] is True
        zt_probes = [p for p in result["probes"] if p["provider"] == "zerotier"]
        assert zt_probes, "ZeroTier not in probes"
        assert zt_probes[0]["reachable"] is True, f"ZT probe failed: {zt_probes[0]}"
        assert result["active"]
        assert result["active"]["provider"] == "zerotier"
    finally:
        stop.set()
        t.join(timeout=3)


# v4.60.1: ZT with active networks + assigned IP but planet OFFLINE
# should still be considered active/connected in the transport
# snapshot. Fixes UI disagreement where the URL worked but the
# transport was marked down.
def test_zerotier_snapshot_lan_only_connected():
    """Planet OFFLINE + active LAN network + IP -> active=True, connected=True."""
    def _stub():
        return {
            "ok": True, "installed": True, "backend": "cli",
            "zerotier": {"node_id": "aabbccddee", "version": "1.16",
                         "connected": False, "online": False},
            "networks": [{"nwid": "abcdef0123456789", "active": True,
                          "assignedAddresses": ["10.57.0.1/24"]}],
            "active_count": 1,
        }
    snap = _zerotier_snapshot(_stub, port=8765)
    assert snap["active"] is True, "active must be True with active LAN"
    assert snap["connected"] is True, "connected must be True (superset)"
    assert snap["planet_connected"] is False, "planet honestly reported offline"
    assert snap["public_url"] == "http://10.57.0.1:8765"


def test_zerotier_snapshot_planet_online_still_reports_planet_connected():
    """Backwards compat: when the CLI reports connected=True (planet up),
    planet_connected should be True too."""
    def _stub():
        return {
            "ok": True, "installed": True,
            "zerotier": {"node_id": "aabbccddee", "connected": True, "online": True},
            "networks": [{"nwid": "abcdef0123456789", "active": True,
                          "assignedAddresses": ["10.57.0.1/24"]}],
            "active_count": 1,
        }
    snap = _zerotier_snapshot(_stub, port=8765)
    assert snap["planet_connected"] is True
    assert snap["connected"] is True
    assert snap["active"] is True


def test_zerotier_snapshot_offline_and_no_networks_stays_inactive():
    """Planet OFFLINE + no active networks -> honestly inactive."""
    def _stub():
        return {
            "ok": True, "installed": True,
            "zerotier": {"connected": False}, "networks": [], "active_count": 0,
        }
    snap = _zerotier_snapshot(_stub, port=8765)
    assert snap["active"] is False
    assert snap["connected"] is False
    assert snap["planet_connected"] is False

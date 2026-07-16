"""Tests for GET /v1/zerotier/peers (v4.4.0).

Covers pure-Python classifier logic (no CLI/network needed) plus
route+wiring guards mirrored on /v1/exec/stream and /v1/exec/script.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.admin.zerotier_peers import (  # noqa: E402
    _classify_peer,
    _direct_hint,
    _peers_summary,
    _split_ip_port,
    zerotier_peers,
)


# ---------------------------------------------------------------------------
# Route + wiring guards
# ---------------------------------------------------------------------------
def test_zerotier_peers_route_in_registry():
    from arena.route_registry.registry import ROUTES
    keys = {(m, p) for (m, p, *_rest) in ROUTES}
    assert ("GET", "/v1/zerotier/peers") in keys


def test_zerotier_peers_route_wired_into_app():
    app = ub.make_app({
        "token": "test", "profile": "owner-shell", "root": Path("/tmp"),
        "active_exec": 0, "max_concurrent": 3, "audit": "audit",
        "timeout": 60, "max_timeout": 3600, "max_output": 2000000,
        "allow_any_cwd": False, "semaphore": asyncio.Semaphore(1),
    })
    paths = {
        (r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter"))
        for r in app.router.routes()
    }
    assert ("GET", "/v1/zerotier/peers") in paths


def test_admin_handlers_expose_zerotier_peers():
    """The AdminHandlers dataclass must expose zerotier_peers so the
    wiring layer can map it into the handler registry."""
    from arena.admin.handlers import AdminHandlers
    assert "zerotier_peers" in AdminHandlers.__dataclass_fields__


def test_platform_wiring_exposes_zerotier_peers():
    """arena/wiring/platform.py must map handle_v1_zerotier_peers so
    the route registry can dispatch to it. Regression guard against
    silent dropouts when adding new handlers."""
    from pathlib import Path as _P
    text = _P("arena/wiring/platform.py").read_text(encoding="utf-8")
    assert "handle_v1_zerotier_peers" in text
    assert "handlers.zerotier_peers" in text


# ---------------------------------------------------------------------------
# Classifier -- pure Python, deterministic, no network / CLI
# ---------------------------------------------------------------------------
def _peer(role, tunneled=False, paths=None, latency=100, addr="abcdef1234"):
    return {
        "address": addr, "role": role, "latency": latency,
        "version": "1.16.2", "tunneled": tunneled,
        "paths": paths or [],
    }


def _path(address, active=True, expired=False, preferred=False):
    return {"address": address, "active": active, "expired": expired,
            "preferred": preferred, "lastReceive": 0, "lastSend": 0}


def test_classify_root_peer():
    """PLANET / MOON peers are roots -- never labelled relay themselves."""
    assert _classify_peer(_peer("PLANET"), set()) == "root"
    assert _classify_peer(_peer("MOON"), set()) == "root"


def test_classify_tunneled_peer():
    """A tunneled LEAF is on TCP fallback regardless of paths."""
    peer = _peer("LEAF", tunneled=True,
                 paths=[_path("1.2.3.4/9993")])
    assert _classify_peer(peer, set()) == "tunneled"


def test_classify_none_peer_when_no_active_path():
    """A LEAF with no active non-expired paths -> unreachable."""
    peer = _peer("LEAF", paths=[
        _path("1.2.3.4/9993", active=False),
        _path("5.6.7.8/9993", expired=True),
    ])
    assert _classify_peer(peer, set()) == "none"


def test_classify_relay_when_all_paths_are_root_ips():
    """LEAF whose only active path goes through a PLANET IP -> relay."""
    root_ips = {"144.202.83.167"}
    peer = _peer("LEAF", paths=[_path("144.202.83.167/21053")])
    assert _classify_peer(peer, root_ips) == "relay"


def test_classify_direct_when_at_least_one_path_is_non_root():
    """A single P2P path is enough to call it direct even if a relay
    path is also active (ZeroTier keeps both around during transition)."""
    root_ips = {"144.202.83.167"}
    peer = _peer("LEAF", paths=[
        _path("144.202.83.167/21053"),
        _path("192.168.1.42/9993"),
    ])
    assert _classify_peer(peer, root_ips) == "direct"


def test_split_ip_port_ipv4_and_ipv6():
    assert _split_ip_port("144.202.83.167/21053") == ("144.202.83.167", "21053")
    assert _split_ip_port("[2605:9880::19]/9993") == ("2605:9880::19", "9993")
    # IPv6 without brackets: rpartition on '/' still gives host/port cleanly
    # because the address in ZT output uses '/' as the separator.
    host, port = _split_ip_port("2605:9880:400:c3:254:f2bc:a1f7:19/9993")
    assert port == "9993"
    assert host.startswith("2605:")
    # Malformed / empty inputs
    assert _split_ip_port("") == ("", "")
    assert _split_ip_port("no-slash") == ("no-slash", "")


# ---------------------------------------------------------------------------
# Summary + hints
# ---------------------------------------------------------------------------
def test_peers_summary_counts_and_ratio():
    peers = [
        {"path_kind": "direct", "role": "LEAF", "latency_ms": 30},
        {"path_kind": "direct", "role": "LEAF", "latency_ms": 40},
        {"path_kind": "relay",  "role": "LEAF", "latency_ms": 200},
        {"path_kind": "root",   "role": "PLANET", "latency_ms": 75},
        {"path_kind": "none",   "role": "LEAF", "latency_ms": -1},
    ]
    s = _peers_summary(peers)
    assert s["peer_count"] == 5
    assert s["leaf_total"] == 4          # 3 reachable LEAFs + 1 unreachable
    assert s["leaf_direct"] == 2
    assert s["leaf_relay"] == 1
    assert s["leaf_tunneled"] == 0
    assert s["leaf_unreachable"] == 1
    assert s["leaf_reachable"] == 3
    assert 0.4 < s["direct_ratio"] < 0.6  # 2/4 = 0.5
    assert s["leaf_latency_ms_min"] == 30
    assert s["leaf_latency_ms_max"] == 200


def test_direct_hint_when_all_relayed():
    hint = _direct_hint({"leaf_total": 3, "leaf_direct": 0,
                         "leaf_tunneled": 0})
    assert hint is not None
    assert "P2P" in hint or "UDP 9993" in hint


def test_direct_hint_when_all_tunneled_mentions_udp():
    hint = _direct_hint({"leaf_total": 2, "leaf_direct": 0,
                         "leaf_tunneled": 2})
    assert hint is not None
    assert "UDP" in hint


def test_direct_hint_none_when_all_direct():
    hint = _direct_hint({"leaf_total": 2, "leaf_direct": 2,
                         "leaf_tunneled": 0})
    assert hint is None


def test_direct_hint_partial_direct_mentions_counts():
    hint = _direct_hint({"leaf_total": 3, "leaf_direct": 1,
                         "leaf_tunneled": 0})
    assert hint is not None
    assert "1/3" in hint


def test_direct_hint_returns_none_when_no_leafs():
    assert _direct_hint({"leaf_total": 0, "leaf_direct": 0,
                         "leaf_tunneled": 0}) is None


# ---------------------------------------------------------------------------
# Top-level entry point smoke -- no network needed; we monkey-patch
# ---------------------------------------------------------------------------
def test_zerotier_peers_returns_stable_shape_when_uninstalled(monkeypatch):
    """When neither authtoken nor CLI is present, return a stable
    error-shape response (not a bare exception)."""
    from arena.admin import zerotier_peers as mod
    monkeypatch.setattr(mod, "_read_token", lambda: (None, None))
    monkeypatch.setattr(mod, "_cli_candidates", lambda: [])
    result = zerotier_peers()
    assert result["ok"] is False
    assert result["backend"] == "none"
    assert result["installed"] is False
    assert result["peers"] == []
    assert result["summary"]["peer_count"] == 0
    assert "hint" in result
    assert "error" in result


def test_zerotier_peers_ok_shape_via_http_stub(monkeypatch):
    """Simulated HTTP path: peers are classified end-to-end without a
    real ZeroTier daemon."""
    from arena.admin import zerotier_peers as mod
    monkeypatch.setattr(mod, "_read_token", lambda: ("faketoken", "/tmp/tok"))

    def _fake_http(path, token):
        assert path == "/peer"
        assert token == "faketoken"
        return [
            {  # our own node observed by a root
                "address": "cafe04eba9", "role": "PLANET", "latency": 75,
                "version": "1.16.2", "tunneled": False,
                "paths": [{"active": True, "expired": False,
                           "address": "50.7.252.138/9993",
                           "lastReceive": 1, "lastSend": 1}],
            },
            {  # relayed LEAF -- all active paths go through the PLANET above
                "address": "0e5d1686dd", "role": "LEAF", "latency": 460,
                "version": "1.16.2", "tunneled": False,
                "paths": [{"active": True, "expired": False,
                           "address": "50.7.252.138/21053",
                           "lastReceive": 1, "lastSend": 1}],
            },
            {  # direct LEAF -- has a non-root path
                "address": "778cde7190", "role": "LEAF", "latency": 30,
                "version": "1.16.2", "tunneled": False,
                "paths": [{"active": True, "expired": False,
                           "address": "192.168.1.10/9993",
                           "lastReceive": 1, "lastSend": 1}],
            },
        ]

    monkeypatch.setattr(mod, "_http_get", _fake_http)
    result = zerotier_peers()
    assert result["ok"] is True
    assert result["backend"] == "http"
    assert result["installed"] is True
    kinds = {p["address"]: p["path_kind"] for p in result["peers"]}
    assert kinds["cafe04eba9"] == "root"
    assert kinds["0e5d1686dd"] == "relay"
    assert kinds["778cde7190"] == "direct"
    assert result["summary"]["leaf_direct"] == 1
    assert result["summary"]["leaf_relay"] == 1

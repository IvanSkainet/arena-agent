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
    """PLANET / MOON peers are roots -- never labelled relay themselves.

    v4.5.0: _classify_peer now returns (path_kind, relay_via).
    """
    assert _classify_peer(_peer("PLANET"), set()) == ("root", None)
    assert _classify_peer(_peer("MOON"), set()) == ("root", None)


def test_classify_tunneled_peer():
    """A tunneled LEAF is on TCP fallback regardless of paths."""
    peer = _peer("LEAF", tunneled=True,
                 paths=[_path("1.2.3.4/9993")])
    assert _classify_peer(peer, set()) == ("tunneled", None)


def test_classify_none_peer_when_no_active_path():
    """A LEAF with no active non-expired paths -> unreachable."""
    peer = _peer("LEAF", paths=[
        _path("1.2.3.4/9993", active=False),
        _path("5.6.7.8/9993", expired=True),
    ])
    assert _classify_peer(peer, set()) == ("none", None)


def test_classify_relay_when_all_paths_are_root_ips():
    """LEAF whose only active path goes through a PLANET IP -> relay
    with relay_via="planet"."""
    root_ips = {"144.202.83.167"}
    peer = _peer("LEAF", paths=[_path("144.202.83.167/21053")])
    assert _classify_peer(peer, root_ips) == ("relay", "planet")


def test_classify_direct_when_at_least_one_path_is_non_root_udp_9993():
    """A single P2P path (non-root IP + port 9993) is enough to call
    it direct even if a relay path is also active (ZeroTier keeps
    both around during transition). v4.5.0: port matters now."""
    root_ips = {"144.202.83.167"}
    peer = _peer("LEAF", paths=[
        _path("144.202.83.167/21053"),
        _path("192.168.1.42/9993"),
    ])
    assert _classify_peer(peer, root_ips) == ("direct", None)


# ---------------------------------------------------------------------------
# v4.5.0 refinement: non-root IP + non-9993 port = TCP-infra relay
# ---------------------------------------------------------------------------
def test_classify_tcp_infra_relay_when_non_root_ip_on_high_port():
    """LEAF whose active path goes to a non-PLANET IP but on a high
    random port (23649) is on ZeroTier TCP-relay infrastructure, not
    P2P UDP. Must be labelled relay + relay_via=tcp-infra so the
    Dashboard hint matches the observation."""
    root_ips = {"1.2.3.4"}  # deliberately mismatched
    peer = _peer("LEAF", paths=[_path("144.202.83.167/23649")])
    assert _classify_peer(peer, root_ips) == ("relay", "tcp-infra")


def test_classify_direct_preferred_over_tcp_infra_when_both_active():
    """If both a TCP-infra path AND a real P2P UDP path are active
    (rare, but ZeroTier does surface it during a transition), the
    P2P path wins -- an agent on a direct link is still on a direct
    link even if a fallback is warm."""
    root_ips: set[str] = set()
    peer = _peer("LEAF", paths=[
        _path("144.202.83.167/23649"),   # tcp-infra
        _path("10.0.0.5/9993"),           # p2p udp
    ])
    assert _classify_peer(peer, root_ips) == ("direct", None)


def test_classify_relay_planet_when_root_and_tcp_infra_both_active():
    """If a peer has BOTH a PLANET path AND a TCP-infra path but no
    P2P UDP, the tcp-infra label wins because it is the most specific
    non-root observation. Guards against silently downgrading a
    tcp-infra relay to a plain planet-relay when a root also happens
    to be reachable at the same moment."""
    root_ips = {"1.1.1.1"}
    peer = _peer("LEAF", paths=[
        _path("1.1.1.1/9993"),            # planet
        _path("2.2.2.2/23649"),           # tcp-infra
    ])
    assert _classify_peer(peer, root_ips) == ("relay", "tcp-infra")


def test_is_direct_udp_port_accepts_9993_only():
    """Port 9993 is the ZeroTier default; anything else is treated
    as not-a-P2P-port for classification purposes. Empty / garbage
    inputs return False so we err toward 'relay' rather than a
    false-positive 'direct'."""
    from arena.admin.zerotier_peers import _is_direct_udp_port
    assert _is_direct_udp_port("9993") is True
    assert _is_direct_udp_port("23649") is False
    assert _is_direct_udp_port("23007") is False
    assert _is_direct_udp_port("443") is False
    assert _is_direct_udp_port("") is False
    assert _is_direct_udp_port("garbage") is False


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
        {"path_kind": "direct", "role": "LEAF", "latency_ms": 30, "relay_via": None},
        {"path_kind": "direct", "role": "LEAF", "latency_ms": 40, "relay_via": None},
        {"path_kind": "relay",  "role": "LEAF", "latency_ms": 200, "relay_via": "planet"},
        {"path_kind": "root",   "role": "PLANET", "latency_ms": 75, "relay_via": None},
        {"path_kind": "none",   "role": "LEAF", "latency_ms": -1, "relay_via": None},
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
    # v4.5.0: relay_via breakdown must sum to leaf_relay.
    assert s["leaf_relay_planet"] == 1
    assert s["leaf_relay_tcp_infra"] == 0


def test_peers_summary_relay_via_breakdown_sums_to_leaf_relay():
    """Mixed planet / tcp-infra relays must be split correctly in the
    summary and the split must add up to the aggregate leaf_relay."""
    peers = [
        {"path_kind": "relay",  "role": "LEAF", "relay_via": "planet"},
        {"path_kind": "relay",  "role": "LEAF", "relay_via": "tcp-infra"},
        {"path_kind": "relay",  "role": "LEAF", "relay_via": "tcp-infra"},
        {"path_kind": "direct", "role": "LEAF", "relay_via": None},
    ]
    s = _peers_summary(peers)
    assert s["leaf_relay"] == 3
    assert s["leaf_relay_planet"] == 1
    assert s["leaf_relay_tcp_infra"] == 2
    assert s["leaf_relay_planet"] + s["leaf_relay_tcp_infra"] == s["leaf_relay"]


def test_direct_hint_when_all_relayed_via_planet():
    """v4.5.0: hints now take relay_via breakdown. Pure planet relay
    keeps the classic hint mentioning PLANET."""
    hint = _direct_hint({"leaf_total": 3, "leaf_direct": 0,
                         "leaf_tunneled": 0,
                         "leaf_relay_planet": 3, "leaf_relay_tcp_infra": 0})
    assert hint is not None
    assert "PLANET" in hint
    assert "UDP 9993" in hint


def test_direct_hint_when_all_relayed_via_tcp_infra_mentions_it():
    """When TCP-infra dominates, the hint must name that transport so
    the observation ('non-9993 ports on non-PLANET IPs') actually
    matches the message. Otherwise the user reads a message about
    PLANET while the peers list shows non-PLANET IPs."""
    hint = _direct_hint({"leaf_total": 2, "leaf_direct": 0,
                         "leaf_tunneled": 0,
                         "leaf_relay_planet": 0, "leaf_relay_tcp_infra": 2})
    assert hint is not None
    assert "TCP-relay infrastructure" in hint
    assert "UDP 9993" in hint


def test_direct_hint_when_all_tunneled_mentions_udp():
    hint = _direct_hint({"leaf_total": 2, "leaf_direct": 0,
                         "leaf_tunneled": 2,
                         "leaf_relay_planet": 0, "leaf_relay_tcp_infra": 0})
    assert hint is not None
    assert "UDP" in hint


def test_direct_hint_none_when_all_direct():
    hint = _direct_hint({"leaf_total": 2, "leaf_direct": 2,
                         "leaf_tunneled": 0,
                         "leaf_relay_planet": 0, "leaf_relay_tcp_infra": 0})
    assert hint is None


def test_direct_hint_partial_direct_mentions_counts():
    hint = _direct_hint({"leaf_total": 3, "leaf_direct": 1,
                         "leaf_tunneled": 0,
                         "leaf_relay_planet": 2, "leaf_relay_tcp_infra": 0})
    assert hint is not None
    assert "1/3" in hint


def test_direct_hint_returns_none_when_no_leafs():
    assert _direct_hint({"leaf_total": 0, "leaf_direct": 0,
                         "leaf_tunneled": 0,
                         "leaf_relay_planet": 0, "leaf_relay_tcp_infra": 0}) is None


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
    real ZeroTier daemon. v4.5.0: verifies relay_via distinguishes
    PLANET-relayed peers from TCP-infra-relayed ones."""
    from arena.admin import zerotier_peers as mod
    monkeypatch.setattr(mod, "_read_token", lambda: ("faketoken", "/tmp/tok"))

    def _fake_http(path, token):
        assert path == "/peer"
        assert token == "faketoken"
        return [
            {  # a PLANET root
                "address": "cafe04eba9", "role": "PLANET", "latency": 75,
                "version": "1.16.2", "tunneled": False,
                "paths": [{"active": True, "expired": False,
                           "address": "50.7.252.138/9993",
                           "lastReceive": 1, "lastSend": 1}],
            },
            {  # PLANET-relayed LEAF -- path goes through the PLANET's IP
                "address": "0e5d1686dd", "role": "LEAF", "latency": 460,
                "version": "1.16.2", "tunneled": False,
                "paths": [{"active": True, "expired": False,
                           "address": "50.7.252.138/21053",
                           "lastReceive": 1, "lastSend": 1}],
            },
            {  # TCP-infra-relayed LEAF -- non-root IP but non-9993 port
                "address": "abc1234def", "role": "LEAF", "latency": 300,
                "version": "1.16.2", "tunneled": False,
                "paths": [{"active": True, "expired": False,
                           "address": "144.202.83.167/23649",
                           "lastReceive": 1, "lastSend": 1}],
            },
            {  # truly direct LEAF -- non-root IP on 9993
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

    by_addr = {p["address"]: p for p in result["peers"]}
    assert by_addr["cafe04eba9"]["path_kind"] == "root"
    assert by_addr["cafe04eba9"]["relay_via"] is None
    assert by_addr["0e5d1686dd"]["path_kind"] == "relay"
    assert by_addr["0e5d1686dd"]["relay_via"] == "planet"
    assert by_addr["abc1234def"]["path_kind"] == "relay"
    assert by_addr["abc1234def"]["relay_via"] == "tcp-infra"
    assert by_addr["778cde7190"]["path_kind"] == "direct"
    assert by_addr["778cde7190"]["relay_via"] is None

    assert result["summary"]["leaf_direct"] == 1
    assert result["summary"]["leaf_relay"] == 2
    assert result["summary"]["leaf_relay_planet"] == 1
    assert result["summary"]["leaf_relay_tcp_infra"] == 1

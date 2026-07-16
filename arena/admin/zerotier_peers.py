"""ZeroTier peer introspection (v4.4.0).

Answers the question **"is my ZeroTier connection direct P2P or is it
being relayed through a PLANET root?"** — the same question the user
asked when they said "may be we can do it Direct like in Tailscale".
Direct peer-to-peer paths give lower latency and higher stability
than relayed traffic, but the state ``zerotier-cli status`` prints
tells you the node is *online* without telling you *how*.

Public entry point: :func:`zerotier_peers` — returns per-peer
classification (``direct`` / ``relay`` / ``root`` / ``tunneled`` /
``none``) plus a tiny summary the Dashboard's Network Status card
can render without any extra math.

Cross-platform: uses the same HTTP-preferred / CLI-fallback stack as
:mod:`arena.admin.zerotier` (``_read_token`` → HTTP ``/peer`` first,
otherwise ``zerotier-cli -j peers``, honouring the optional
``zerotier-cli-wrapper`` sudo helper on Linux). No sudo is ever
invoked directly from this module — that stays a user opt-in.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from arena.admin.zerotier import (
    HTTP_API,
    _cli_candidates,
    _cli_source,
    _http_get,
    _install_hint,
    _permission_hint,
    _read_token,
    _run_cli,
)


def _split_ip_port(address: str) -> tuple[str, str]:
    """``144.202.83.167/21053`` → (``144.202.83.167``, ``21053``).

    Handles bracketed IPv6 like ``[fe80::1]/9993`` and IPv6 with a
    single colon suffix like ``2605:...:19/9993``. When we can't
    tell, return the raw string as the host and empty port — the
    classifier only uses host equality anyway.
    """
    if not address or "/" not in address:
        return address, ""
    host, _, port = address.rpartition("/")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host, port


def _classify_peer(peer: dict[str, Any], root_ips: set[str]) -> str:
    """Return one of: ``direct`` | ``relay`` | ``root`` | ``tunneled`` | ``none``.

    Rules (in order):

    * ``role == "PLANET"`` or ``"MOON"`` → ``root``. Peer *is* the
      relay, so "relayed through itself" is meaningless.
    * ``peer.tunneled`` truthy → ``tunneled``. TCP-fallback path
      via api.zerotier.com:443 or similar — worst case, works over
      any HTTPS-only network.
    * No active non-expired path → ``none``. Peer is known but not
      currently reachable.
    * Any active path whose host IP is NOT one of the PLANET/MOON
      IPs → ``direct``. This peer talks to us via P2P UDP.
    * Otherwise (every active path goes through a root) → ``relay``.
    """
    role = str(peer.get("role") or "").upper()
    if role in {"PLANET", "MOON"}:
        return "root"
    if peer.get("tunneled"):
        return "tunneled"

    active_paths = [
        p for p in peer.get("paths") or []
        if p.get("active") and not p.get("expired")
    ]
    if not active_paths:
        return "none"

    for path in active_paths:
        host, _ = _split_ip_port(str(path.get("address") or ""))
        if host and host not in root_ips:
            return "direct"
    return "relay"


def _peers_summary(peers: list[dict[str, Any]]) -> dict[str, Any]:
    """Small counters block for the Network Status card."""
    counts = {"direct": 0, "relay": 0, "root": 0, "tunneled": 0, "none": 0}
    leaf_latencies: list[int] = []
    for p in peers:
        counts[p.get("path_kind", "none")] = counts.get(p.get("path_kind", "none"), 0) + 1
        if p.get("role") == "LEAF":
            # Normalized peers use ``latency_ms``; accept raw
            # ``latency`` too so this helper works on both.
            lat = p.get("latency_ms")
            if lat is None:
                lat = p.get("latency")
            if isinstance(lat, int) and lat >= 0:
                leaf_latencies.append(lat)

    leaf_total = counts["direct"] + counts["relay"] + counts["tunneled"] + counts["none"]
    leaf_reachable = counts["direct"] + counts["relay"] + counts["tunneled"]

    summary: dict[str, Any] = {
        "peer_count": len(peers),
        "counts": counts,
        "leaf_total": leaf_total,
        "leaf_reachable": leaf_reachable,
        "leaf_direct": counts["direct"],
        "leaf_relay": counts["relay"],
        "leaf_tunneled": counts["tunneled"],
        "leaf_unreachable": counts["none"],
        "direct_ratio": (counts["direct"] / leaf_total) if leaf_total else 0.0,
    }
    if leaf_latencies:
        summary["leaf_latency_ms_min"] = min(leaf_latencies)
        summary["leaf_latency_ms_max"] = max(leaf_latencies)
        summary["leaf_latency_ms_avg"] = round(
            sum(leaf_latencies) / len(leaf_latencies), 1
        )
    return summary


def _direct_hint(summary: dict[str, Any]) -> str | None:
    """Actionable hint when every LEAF is going through a relay.

    Deliberately terse — the Dashboard shows this inline and the
    long form lives in the docs. Focus on the two knobs a normal
    user actually has (UDP 9993 outbound + NAT hole-punching).
    """
    leaf_total = summary.get("leaf_total", 0)
    if leaf_total == 0:
        return None
    direct = summary.get("leaf_direct", 0)
    tunneled = summary.get("leaf_tunneled", 0)
    if tunneled == leaf_total and tunneled > 0:
        return (
            "All LEAF peers are on TCP-tunneled paths (api.zerotier.com:443). "
            "This usually means UDP is blocked outbound — check the firewall "
            "on this host and any upstream router."
        )
    if direct == 0 and leaf_total > 0:
        return (
            "Every LEAF peer is routed through a PLANET relay — no direct "
            "P2P paths yet. Allow UDP 9993 outbound on both peers and, if "
            "either side is behind a strict NAT, enable UPnP / NAT-PMP on "
            "the router so ZeroTier's hole-punching can succeed."
        )
    if direct < leaf_total:
        return (
            f"{direct}/{leaf_total} LEAF peers on direct P2P; the rest are "
            "relayed. Direct paths usually establish within a few seconds "
            "after both peers start exchanging traffic."
        )
    return None


def _normalize_peer(peer: dict[str, Any], root_ips: set[str]) -> dict[str, Any]:
    """Trim the raw ``zerotier-cli -j peers`` entry to the fields the
    Dashboard / agents actually consume. Skip the noisy ones
    (``localSocket``, ``trustedPathId``, ``preferred``…) but keep the
    ``address`` + ``lastReceive`` so operators can debug in the raw JSON."""
    active_paths = [
        {
            "address": str(p.get("address") or ""),
            "last_receive": p.get("lastReceive"),
            "last_send": p.get("lastSend"),
            "preferred": bool(p.get("preferred")),
        }
        for p in peer.get("paths") or []
        if p.get("active") and not p.get("expired")
    ]
    path_kind = _classify_peer(peer, root_ips)
    latency = peer.get("latency")
    if not isinstance(latency, int):
        latency = -1
    return {
        "address": str(peer.get("address") or ""),
        "role": str(peer.get("role") or "").upper() or "?",
        "version": str(peer.get("version") or "-"),
        "latency_ms": latency,
        "tunneled": bool(peer.get("tunneled")),
        "path_kind": path_kind,
        "active_paths": active_paths,
        "path_count": len(peer.get("paths") or []),
        "active_path_count": len(active_paths),
    }


def _root_ips_from_peers(raw_peers: list[dict[str, Any]]) -> set[str]:
    """Collect every host address advertised by PLANET/MOON peers so
    the classifier knows what counts as a relay path."""
    roots: set[str] = set()
    for peer in raw_peers:
        role = str(peer.get("role") or "").upper()
        if role not in {"PLANET", "MOON"}:
            continue
        for path in peer.get("paths") or []:
            host, _ = _split_ip_port(str(path.get("address") or ""))
            if host:
                roots.add(host)
    return roots


def _peers_via_http(token: str) -> list[dict[str, Any]] | None:
    """Query the local ``/peer`` endpoint. Returns the raw list on
    success, ``None`` if the daemon is not reachable."""
    peers = _http_get("/peer", token)
    if isinstance(peers, list):
        return [p for p in peers if isinstance(p, dict)]
    return None


def _peers_via_cli(cli: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Query ``zerotier-cli -j peers``. Returns ``(peers, None)`` on
    success or ``(None, error_message)`` on failure."""
    try:
        proc = _run_cli(cli, ["-j", "peers"], timeout=10)
    except FileNotFoundError:
        return None, f"binary vanished: {cli}"
    except subprocess.TimeoutExpired:
        return None, "zerotier-cli peers timed out"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or f"exit={proc.returncode}").strip()
        return None, err[:400]
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        return None, f"peers JSON parse error: {exc}"
    if not isinstance(data, list):
        return None, "peers output was not a JSON array"
    return [p for p in data if isinstance(p, dict)], None


def zerotier_peers() -> dict[str, Any]:
    """Return classified ZeroTier peers (v4.4.0).

    Response shape (stable):

    ::

        {
          "ok": bool,
          "installed": bool,
          "backend": "http" | "cli" | "none",
          "cli_source": "direct" | "sudo-wrapper" | None,
          "cli_path": str | None,
          "authtoken_path": str | None,
          "peers": [
            {
              "address": "0e5d1686dd",
              "role": "LEAF" | "PLANET" | "MOON",
              "version": "1.16.2",
              "latency_ms": 166,           # -1 if unknown
              "tunneled": false,
              "path_kind": "direct" | "relay" | "root" | "tunneled" | "none",
              "active_paths": [
                {"address": "...", "last_receive": 1784, "last_send": 1784, "preferred": true}
              ],
              "path_count": 3,
              "active_path_count": 3
            }, ...
          ],
          "summary": {"peer_count", "counts", "leaf_direct", "leaf_relay", ...},
          "hint": str | None
        }
    """
    result: dict[str, Any] = {
        "ok": True,
        "installed": False,
        "backend": "none",
        "cli_source": None,
        "cli_path": None,
        "authtoken_path": None,
        "peers": [],
        "summary": {"peer_count": 0, "counts": {}, "leaf_total": 0,
                    "leaf_reachable": 0, "leaf_direct": 0, "leaf_relay": 0,
                    "leaf_tunneled": 0, "leaf_unreachable": 0,
                    "direct_ratio": 0.0},
        "hint": None,
    }

    raw_peers: list[dict[str, Any]] | None = None
    last_error: str | None = None

    token, token_path = _read_token()
    result["authtoken_path"] = token_path
    if token:
        raw_peers = _peers_via_http(token)
        if raw_peers is not None:
            result["installed"] = True
            result["backend"] = "http"
        else:
            last_error = f"ZeroTier local API at {HTTP_API}/peer did not respond"

    if raw_peers is None:
        for cli in _cli_candidates():
            peers, err = _peers_via_cli(cli)
            if peers is not None:
                raw_peers = peers
                result["installed"] = True
                result["backend"] = "cli"
                result["cli_path"] = cli
                result["cli_source"] = _cli_source(cli)
                break
            last_error = err

    if raw_peers is None:
        result["ok"] = False
        if not token and not _cli_candidates():
            result["hint"] = _install_hint()
            result["error"] = "ZeroTier does not appear to be installed"
        else:
            result["installed"] = True
            result["error"] = (
                "ZeroTier is installed but the Bridge cannot read peers"
            )
            result["hint"] = _permission_hint(last_error or "unknown")
        return result

    root_ips = _root_ips_from_peers(raw_peers)
    result["peers"] = [_normalize_peer(p, root_ips) for p in raw_peers]
    result["summary"] = _peers_summary(result["peers"])
    hint = _direct_hint(result["summary"])
    if hint:
        result["hint"] = hint
    return result


__all__ = [
    "zerotier_peers",
    # Re-exported so tests can pin them without depending on internal names.
    "_classify_peer",
    "_peers_summary",
    "_direct_hint",
    "_split_ip_port",
]

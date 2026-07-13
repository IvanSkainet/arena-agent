"""Unified tunnel/remote-access manager.

The Bridge can expose itself to the outside world through several providers:

  * ``tailscale``  — Tailscale Funnel (public HTTPS through Tailnet's edge)
  * ``cloudflared`` — Cloudflare quick tunnel (public HTTPS via *.trycloudflare.com)
  * ``zerotier``   — ZeroTier overlay network (private IP over ZeroTier)

Each provider has independent semantics and reliability characteristics.
Historically the Bridge exposed them as separate endpoints, which meant
clients had to know about each one and had no way to say "just give me a
reachable URL, whatever works".

This module provides a single fan-in facade with priorities and
auto-failover:

    priorities = ["tailscale", "cloudflared", "zerotier"]

    tunnels_status()   -> per-provider snapshot with a suggested "active" one
    tunnels_start()    -> start every provider in priority order, stop on
                          the first that goes healthy
    tunnels_stop()     -> stop every provider we manage
    tunnels_active()   -> resolve the best current endpoint for a client

The module is deliberately provider-agnostic and cross-platform. Provider
callables are injected so tests can substitute them without going near the
network.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any


DEFAULT_PRIORITY = ("tailscale", "cloudflared", "zerotier")


def _priority_from_env() -> tuple[str, ...]:
    """Optional override via ARENA_TUNNEL_PRIORITY=tailscale,cloudflared,zerotier."""
    raw = os.environ.get("ARENA_TUNNEL_PRIORITY", "").strip()
    if not raw:
        return DEFAULT_PRIORITY
    order = tuple(p.strip().lower() for p in raw.split(",") if p.strip())
    # Keep only providers we know about, preserving user order, then append
    # any known providers the user did not mention so nothing is silently lost.
    known = {p: None for p in DEFAULT_PRIORITY}
    result: list[str] = [p for p in order if p in known]
    for p in DEFAULT_PRIORITY:
        if p not in result:
            result.append(p)
    return tuple(result)


# ---------------------------------------------------------------------------
# Provider adapters — small dataclass-ish dicts describing what each provider
# returns via its own status/start/stop. Keeping this as a thin translation
# layer means each provider module keeps its own implementation without
# leaking here.
# ---------------------------------------------------------------------------
def _tailscale_snapshot(sys_funnel_status_sync: Callable[[], dict[str, Any]] | None) -> dict[str, Any]:
    if sys_funnel_status_sync is None:
        return {
            "provider": "tailscale",
            "available": False,
            "reason": "provider callable not wired",
        }
    try:
        raw = sys_funnel_status_sync() or {}
    except Exception as e:
        return {"provider": "tailscale", "available": False, "error": str(e)[:200]}
    ts = raw.get("tailscale") or {}
    funnel = raw.get("funnel") or {}
    public_url = funnel.get("url") or (ts.get("public_url") if isinstance(ts, dict) else None)
    connected = bool(ts.get("connected"))
    active = bool(funnel.get("active")) or bool(public_url)
    # sys_funnel_status does not always emit an explicit "installed" flag,
    # so infer it: if the underlying call succeeded and reports any state
    # (connected / active / a status string) then tailscale is present.
    installed = (
        bool(ts.get("installed"))
        or connected
        or active
        or bool(ts.get("status"))
        or bool(funnel.get("status"))
    )
    return {
        "provider": "tailscale",
        "installed": installed,
        "connected": connected,
        "active": active,
        "public_url": public_url,
        "public_kind": "https",
        "manageable": True,
        "raw": raw,
    }


def _cloudflared_snapshot(cloudflared_status_sync: Callable[[], dict[str, Any]] | None) -> dict[str, Any]:
    if cloudflared_status_sync is None:
        return {"provider": "cloudflared", "available": False, "reason": "provider callable not wired"}
    try:
        raw = cloudflared_status_sync() or {}
    except Exception as e:
        return {"provider": "cloudflared", "available": False, "error": str(e)[:200]}
    return {
        "provider": "cloudflared",
        "installed": bool(raw.get("installed")),
        "cli_source": raw.get("source"),
        "version": raw.get("version"),
        "active": bool(raw.get("active")),
        "public_url": raw.get("url") or None,
        "public_kind": "https",
        "manageable": True,
        "update_hint": raw.get("update_hint"),
        "raw": raw,
    }


def _zerotier_snapshot(zerotier_status_sync: Callable[[], dict[str, Any]] | None) -> dict[str, Any]:
    if zerotier_status_sync is None:
        return {"provider": "zerotier", "available": False, "reason": "provider callable not wired"}
    try:
        raw = zerotier_status_sync() or {}
    except Exception as e:
        return {"provider": "zerotier", "available": False, "error": str(e)[:200]}
    zt = raw.get("zerotier") or {}
    networks = raw.get("networks") or []
    active_nets = [n for n in networks if n.get("active")]
    # Public "URL" for ZeroTier is the assigned IP on any active network.
    public_ip = None
    for net in active_nets:
        addrs = net.get("assignedAddresses") or []
        if addrs:
            # Prefer plain IPv4 without /prefix.
            first = addrs[0]
            public_ip = first.split("/")[0] if "/" in first else first
            break
    return {
        "provider": "zerotier",
        "installed": bool(raw.get("installed")),
        "backend": raw.get("backend"),
        "cli_source": raw.get("cli_source"),
        "connected": bool(zt.get("connected")),
        "active": bool(zt.get("connected")) and bool(active_nets),
        "public_url": (f"http://{public_ip}:8765" if public_ip else None),
        "public_kind": "http-lan",
        "node_id": zt.get("node_id"),
        "version": zt.get("version"),
        "networks": active_nets,
        "manageable": True,
        "hint": raw.get("hint"),
        "raw": raw,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def tunnels_status(
    *,
    sys_funnel_status_sync: Callable[[], dict[str, Any]] | None = None,
    cloudflared_status_sync: Callable[[], dict[str, Any]] | None = None,
    zerotier_status_sync: Callable[[], dict[str, Any]] | None = None,
    priority: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Return a snapshot of every provider plus a suggested active endpoint."""
    order = priority or _priority_from_env()

    snapshots: dict[str, dict[str, Any]] = {
        "tailscale": _tailscale_snapshot(sys_funnel_status_sync),
        "cloudflared": _cloudflared_snapshot(cloudflared_status_sync),
        "zerotier": _zerotier_snapshot(zerotier_status_sync),
    }

    ordered = [snapshots[name] for name in order if name in snapshots]

    active = None
    for snap in ordered:
        if snap.get("active") and snap.get("public_url"):
            active = {
                "provider": snap["provider"],
                "public_url": snap["public_url"],
                "public_kind": snap.get("public_kind", "unknown"),
            }
            break

    return {
        "ok": True,
        "priority": list(order),
        "providers": ordered,
        "active": active,
    }


def tunnels_active(
    *,
    sys_funnel_status_sync: Callable[[], dict[str, Any]] | None = None,
    cloudflared_status_sync: Callable[[], dict[str, Any]] | None = None,
    zerotier_status_sync: Callable[[], dict[str, Any]] | None = None,
    priority: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Return only the currently active endpoint (or an empty object)."""
    snap = tunnels_status(
        sys_funnel_status_sync=sys_funnel_status_sync,
        cloudflared_status_sync=cloudflared_status_sync,
        zerotier_status_sync=zerotier_status_sync,
        priority=priority,
    )
    return {"ok": True, "active": snap.get("active"), "priority": snap.get("priority")}


def tunnels_start(
    *,
    port: int,
    tailscale_funnel_action_sync: Callable[[str, int], dict[str, Any]] | None = None,
    cloudflared_funnel_action_sync: Callable[[str, int], dict[str, Any]] | None = None,
    sys_funnel_status_sync: Callable[[], dict[str, Any]] | None = None,
    cloudflared_status_sync: Callable[[], dict[str, Any]] | None = None,
    zerotier_status_sync: Callable[[], dict[str, Any]] | None = None,
    priority: tuple[str, ...] | None = None,
    stop_on_first_healthy: bool = True,
) -> dict[str, Any]:
    """Start providers in priority order.

    ZeroTier is not "started" per se (join is a network membership action, not
    a tunnel toggle), so it is only reported. Tailscale and cloudflared have
    real start/stop verbs.

    If ``stop_on_first_healthy`` (default) is set, the loop stops as soon as
    one provider is verified active with a public URL. That keeps the Bridge
    from spinning up more upstreams than it needs.
    """
    order = priority or _priority_from_env()
    log: list[dict[str, Any]] = []

    for name in order:
        entry: dict[str, Any] = {"provider": name, "action": "skip"}
        if name == "tailscale" and tailscale_funnel_action_sync is not None:
            entry["action"] = "start"
            try:
                entry["result"] = tailscale_funnel_action_sync("start", port)
            except Exception as e:
                entry["error"] = str(e)[:200]
        elif name == "cloudflared" and cloudflared_funnel_action_sync is not None:
            entry["action"] = "start"
            try:
                entry["result"] = cloudflared_funnel_action_sync("start", port)
            except Exception as e:
                entry["error"] = str(e)[:200]
        elif name == "zerotier":
            # No-op start; users manage ZeroTier network membership out-of-band.
            entry["action"] = "noop"
            entry["result"] = {"ok": True, "note": "ZeroTier membership is managed via /v1/zerotier/network/*"}
        else:
            entry["action"] = "unwired"
        log.append(entry)

        # Check whether the provider we just tried is now healthy. We stop
        # as soon as one is up, but only if it was actually attempted (skip
        # snapshots for "unwired" providers so a stub cloudflared_status_sync
        # returning True cannot mask a failed tailscale start).
        if stop_on_first_healthy and entry["action"] in ("start", "noop"):
            snap = tunnels_status(
                sys_funnel_status_sync=sys_funnel_status_sync,
                cloudflared_status_sync=cloudflared_status_sync,
                zerotier_status_sync=zerotier_status_sync,
                priority=order,
            )
            active = snap.get("active")
            if active and active.get("provider") == name:
                return {"ok": True, "log": log, "active": active, "priority": list(order)}

    # Nothing healthy — return the final snapshot for diagnostics.
    snap = tunnels_status(
        sys_funnel_status_sync=sys_funnel_status_sync,
        cloudflared_status_sync=cloudflared_status_sync,
        zerotier_status_sync=zerotier_status_sync,
        priority=order,
    )
    return {"ok": True, "log": log, "active": snap.get("active"), "priority": list(order)}


def tunnels_stop(
    *,
    port: int,
    tailscale_funnel_action_sync: Callable[[str, int], dict[str, Any]] | None = None,
    cloudflared_funnel_action_sync: Callable[[str, int], dict[str, Any]] | None = None,
    priority: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Stop tunnels we started. ZeroTier is intentionally left alone."""
    order = priority or _priority_from_env()
    log: list[dict[str, Any]] = []
    for name in order:
        entry: dict[str, Any] = {"provider": name, "action": "skip"}
        if name == "tailscale" and tailscale_funnel_action_sync is not None:
            entry["action"] = "stop"
            try:
                entry["result"] = tailscale_funnel_action_sync("stop", port)
            except Exception as e:
                entry["error"] = str(e)[:200]
        elif name == "cloudflared" and cloudflared_funnel_action_sync is not None:
            entry["action"] = "stop"
            try:
                entry["result"] = cloudflared_funnel_action_sync("stop", port)
            except Exception as e:
                entry["error"] = str(e)[:200]
        elif name == "zerotier":
            entry["action"] = "noop"
            entry["result"] = {"ok": True, "note": "ZeroTier membership is not toggled by /v1/tunnels/stop"}
        else:
            entry["action"] = "unwired"
        log.append(entry)
    return {"ok": True, "log": log, "priority": list(order)}

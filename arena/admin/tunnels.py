"""Unified tunnel/remote-access manager.

The Bridge can expose itself to the outside world through several providers:

  * ``tailscale``   — Tailscale Funnel (public HTTPS through Tailnet's edge)
  * ``cloudflared`` — Cloudflare quick tunnel (public HTTPS via *.trycloudflare.com)
  * ``zerotier``    — ZeroTier overlay network (private IP over ZeroTier)
  * ``ngrok``       — ngrok tunnel (public HTTPS via *.ngrok-free.app / paid)
  * ``bore``        — bore relay (raw TCP through bore.pub, no account, v4.47.0)

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
import socket
from collections.abc import Callable
from typing import Any


# v4.1.0: ZeroTier moved ahead of cloudflared in the default order.
# Cloudflared quick-tunnels routinely disconnect on flaky ISP links,
# leaving agents stuck; ZeroTier's overlay is far more stable
# (persistent UDP session, works over NAT/CGNAT, no reliance on a
# public CDN). Tailscale Funnel stays first because it's the
# lowest-friction path when it's available (public HTTPS URL, no
# client config needed on the agent side beyond a Bearer token).
#
# Override with ARENA_TUNNEL_PRIORITY=zerotier,tailscale,cloudflared
# (any subset; missing providers append in the built-in order).
# v4.33.0: ngrok added as a fourth transport, placed last so
# existing operators see the same primary/secondary order they
# had before. Override with ARENA_TUNNEL_PRIORITY to reorder.
# v4.47.0: bore added as a fifth transport, placed after ngrok so
# existing priority behaviour is preserved. bore is picked last on
# purpose -- it is TCP-only (no HTTPS terminate at the relay) and
# leans on the bridge's own self-signed cert + pinning story, so
# it's meant as a zero-account fallback rather than a primary path.
DEFAULT_PRIORITY = ("tailscale", "zerotier", "cloudflared", "ngrok", "bore")


def _priority_from_env() -> tuple[str, ...]:
    """Optional override via ARENA_TUNNEL_PRIORITY=tailscale,zerotier,cloudflared."""
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


def _bore_snapshot(bore_status_sync: Callable[[], dict[str, Any]] | None) -> dict[str, Any]:
    """v4.47.0: fifth transport snapshot. Same shape as the
    cloudflared / ngrok snapshots so downstream code (dashboard,
    agentctl, probe) doesn't have to special-case bore.

    ``public_kind`` is reported as ``"https"`` because the
    outward-facing URL is ``https://<server>:<remote_port>`` --
    bore itself only relays raw TCP, but the bridge terminates
    TLS on the other end of that TCP pipe.
    """
    if bore_status_sync is None:
        return {"provider": "bore", "available": False,
                "reason": "provider callable not wired"}
    try:
        raw = bore_status_sync() or {}
    except Exception as e:
        return {"provider": "bore", "available": False, "error": str(e)[:200]}
    return {
        "provider": "bore",
        "installed": bool(raw.get("installed")),
        "cli_source": raw.get("source"),
        "version": raw.get("version"),
        "active": bool(raw.get("active")),
        "public_url": raw.get("url") or None,
        "public_kind": "https",
        "manageable": True,
        "server": raw.get("server"),
        "update_hint": raw.get("update_hint"),
        "raw": raw,
    }


def _ngrok_snapshot(ngrok_status_sync: Callable[[], dict[str, Any]] | None) -> dict[str, Any]:
    """v4.33.0: same shape as _cloudflared_snapshot -- ngrok wired
    as fourth transport. Snapshot is opt-in: when the sync callable
    isn't provided (older ctx / test rig), we still return a
    well-formed 'available: False' dict so downstream code doesn't
    have to special-case ngrok."""
    if ngrok_status_sync is None:
        return {"provider": "ngrok", "available": False,
                "reason": "provider callable not wired"}
    try:
        raw = ngrok_status_sync() or {}
    except Exception as e:
        return {"provider": "ngrok", "available": False, "error": str(e)[:200]}
    return {
        "provider": "ngrok",
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


def _zerotier_snapshot(
    zerotier_status_sync: Callable[[], dict[str, Any]] | None,
    port: int = 8765,
) -> dict[str, Any]:
    """Return a ZeroTier transport snapshot.

    v4.1.0: also collects every assigned IP (not just the first) so the
    Dashboard/agents can pick an IPv4 explicitly when both v4 and v6
    are handed out, and returns ``public_urls`` as a list of ready-to-
    use ``http://<ip>:<port>`` endpoints for every active network the
    node is a member of. ``public_url`` (singular) stays as the first
    IPv4 endpoint for backwards compatibility with the v3.86.x
    tunnels-status shape.
    """
    if zerotier_status_sync is None:
        return {"provider": "zerotier", "available": False, "reason": "provider callable not wired"}
    try:
        raw = zerotier_status_sync() or {}
    except Exception as e:
        return {"provider": "zerotier", "available": False, "error": str(e)[:200]}
    zt = raw.get("zerotier") or {}
    networks = raw.get("networks") or []
    active_nets = [n for n in networks if n.get("active")]

    # Collect every assigned IP across every active network. Prefer IPv4
    # first (agents typically dial that), then IPv6.
    ipv4_addrs: list[str] = []
    ipv6_addrs: list[str] = []
    for net in active_nets:
        for addr in net.get("assignedAddresses") or []:
            ip = addr.split("/")[0] if "/" in addr else addr
            if ":" in ip:
                ipv6_addrs.append(ip)
            else:
                ipv4_addrs.append(ip)
    all_ips = ipv4_addrs + ipv6_addrs

    public_urls = [
        (f"http://[{ip}]:{port}" if ":" in ip else f"http://{ip}:{port}")
        for ip in all_ips
    ]
    public_url = public_urls[0] if public_urls else None

    # v4.60.1: ZeroTier's "connected" (from `zerotier-cli status`) reports
    # planet-connectivity — whether ZT talks to a root server. On hosts
    # behind restrictive NAT / offline planet, `status` prints OFFLINE
    # even when the daemon happily peers with a local network via cached
    # roots or LAN discovery, and the node has an assigned IP. Previously
    # this made `active=false`, so both Overview (○ installed) and
    # Transports (down) disagreed with reality — the URL http://<ip>:port
    # worked, but the UI said the transport was inactive.
    #
    # Fix: recognise "LAN-only connected" — if there is at least one
    # active network AND an assigned IP, consider the transport active
    # regardless of what CLI status reports for planet-connectivity.
    lan_connected = bool(active_nets) and bool(all_ips)
    connected = bool(zt.get("connected")) or lan_connected
    return {
        "provider": "zerotier",
        "installed": bool(raw.get("installed")),
        "backend": raw.get("backend"),
        "cli_source": raw.get("cli_source"),
        "connected": connected,
        # v4.60.1: was `connected AND active_nets AND all_ips`; the extra
        # `connected` guard is redundant now that `connected` is a superset.
        # Keep active as the stronger predicate: real network with real IP.
        "active": lan_connected,
        "planet_connected": bool(zt.get("connected")),
        "public_url": public_url,
        "public_urls": public_urls,
        "public_kind": "http-lan",
        "node_id": zt.get("node_id"),
        "version": zt.get("version"),
        "assigned_ipv4": ipv4_addrs,
        "assigned_ipv6": ipv6_addrs,
        "networks": active_nets,
        "manageable": True,
        "hint": raw.get("hint"),
        "raw": raw,
    }


# ---------------------------------------------------------------------------
# v4.1.0: transport reachability probes
# ---------------------------------------------------------------------------

def _probe_tcp(host: str, port: int, timeout: float = 1.5) -> dict[str, Any]:
    """Quick TCP-connect probe. Returns
    ``{"ok": bool, "duration_ms": int, "error"?: str}``. Used to
    verify a transport is *actually reachable* rather than just
    "the provider says it started".

    Timeout is deliberately short (1.5s default): a Dashboard tab
    that polls every few seconds shouldn't block on a dead endpoint.
    """
    import time
    start = time.monotonic()
    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        elapsed = (time.monotonic() - start) * 1000
        return {"ok": True, "duration_ms": int(elapsed)}
    except (socket.timeout, TimeoutError):
        return {"ok": False, "error": f"timeout after {timeout}s", "duration_ms": int(timeout * 1000)}
    except OSError as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "duration_ms": int((time.monotonic() - start) * 1000)}
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def _parse_url_host_port(url: str, default_port: int = 8765) -> tuple[str, int]:
    """Extract (host, port) from ``http[s]://host[:port]/...`` or
    ``http://[ipv6]:port/`` and return them.

    Scheme-default ports are honoured: an https URL without an explicit
    port returns 443, an http URL returns 80 (not the bridge's 8765).
    Returns ``("", default_port)`` when the URL doesn't have a scheme
    at all so callers can short-circuit without raising.
    """
    try:
        from urllib.parse import urlparse
        u = urlparse(url)
        host = u.hostname or ""
        if u.port:
            return host, int(u.port)
        # Fall back on scheme default so `https://foo/` reports 443.
        scheme_defaults = {"http": 80, "https": 443, "ws": 80, "wss": 443}
        if u.scheme in scheme_defaults:
            return host, scheme_defaults[u.scheme]
        return host, default_port
    except Exception:
        return "", default_port


def tunnels_probe(
    *,
    sys_funnel_status_sync: Callable[[], dict[str, Any]] | None = None,
    cloudflared_status_sync: Callable[[], dict[str, Any]] | None = None,
    zerotier_status_sync: Callable[[], dict[str, Any]] | None = None,
    ngrok_status_sync: Callable[[], dict[str, Any]] | None = None,
    bore_status_sync: Callable[[], dict[str, Any]] | None = None,
    priority: tuple[str, ...] | None = None,
    port: int = 8765,
    timeout: float = 1.5,
    breaker: Any = None,
) -> dict[str, Any]:
    """v4.1.0: check that each provider's advertised public URL is
    actually reachable from the bridge host.

    Handy for agents: they can call this once to figure out which
    transport is currently useful, rather than trusting the provider's
    self-report (Cloudflared quick-tunnel in particular says "active"
    long after its websocket to Cloudflare has silently died).

    v4.8.0: adds a per-``(provider,host,port)`` circuit breaker so
    a provider that has failed the last N probes in a row is skipped
    for the cooldown window rather than paying another ``timeout``
    seconds per call. Skipped probes still appear in the response as
    ``reachable=False`` with an audit-quality ``skip_reason`` so agents
    know a transport isn't just missing, it's currently in cooldown.
    Pass ``breaker=None`` (default) to use the shared module-level
    breaker; tests pass their own instance.
    """
    from arena.admin.tunnels_breaker import get_default_breaker
    if breaker is None:
        breaker = get_default_breaker()

    snap = tunnels_status(
        sys_funnel_status_sync=sys_funnel_status_sync,
        cloudflared_status_sync=cloudflared_status_sync,
        zerotier_status_sync=zerotier_status_sync,
        ngrok_status_sync=ngrok_status_sync,
        bore_status_sync=bore_status_sync,
        priority=priority,
        port=port,
    )
    probes = []
    for provider in snap.get("providers", []):
        url = provider.get("public_url")
        if not url:
            probes.append({
                "provider": provider.get("provider"),
                "public_url": None,
                "reachable": False,
                "skip_reason": "no public_url",
            })
            continue
        host, port_from_url = _parse_url_host_port(url, default_port=port)
        if not host:
            probes.append({
                "provider": provider.get("provider"),
                "public_url": url,
                "reachable": False,
                "skip_reason": "malformed URL",
            })
            continue
        # For https URLs, skip TCP probe — a working port doesn't mean
        # the TLS/HTTP layer works, and we can't do a full HTTP probe
        # without pulling requests in. Tailscale funnel's public_url
        # is https; trust its own "active" flag there.
        if url.startswith("https://"):
            probes.append({
                "provider": provider.get("provider"),
                "public_url": url,
                "reachable": bool(provider.get("active")),
                "note": "https endpoint — trusted from provider's active flag",
            })
            continue
        # v4.8.0: per-(provider,host,port) circuit breaker. Once N
        # probes fail in a row we stop wasting `timeout` seconds and
        # simply report the breaker state until cooldown elapses.
        breaker_key = f"{provider.get('provider')}|{host}:{port_from_url}"
        if not breaker.allow(breaker_key):
            probes.append({
                "provider": provider.get("provider"),
                "public_url": url,
                "host": host,
                "port": port_from_url,
                "reachable": False,
                "skip_reason": breaker.describe_open(breaker_key)
                                or "circuit-breaker open",
                "breaker_state": "open",
            })
            continue
        result = _probe_tcp(host, port_from_url, timeout=timeout)
        if result["ok"]:
            breaker.record_success(breaker_key)
        else:
            breaker.record_failure(breaker_key, error=result.get("error"))
        probes.append({
            "provider": provider.get("provider"),
            "public_url": url,
            "host": host,
            "port": port_from_url,
            "reachable": bool(result["ok"]),
            "duration_ms": result["duration_ms"],
            "error": result.get("error"),
        })

    reachable = [p for p in probes if p.get("reachable")]
    # Preserve priority order (probes are already in priority order
    # because tunnels_status returns them that way).
    active = reachable[0] if reachable else None
    return {
        "ok": True,
        "priority": snap.get("priority"),
        "probes": probes,
        "active": {
            "provider": active["provider"],
            "public_url": active["public_url"],
        } if active else None,
        "reachable_count": len(reachable),
        # v4.8.0: expose breaker state so ops can see WHY a provider
        # is currently being skipped without needing a debug endpoint.
        "breaker": breaker.snapshot(),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def tunnels_status(
    *,
    sys_funnel_status_sync: Callable[[], dict[str, Any]] | None = None,
    cloudflared_status_sync: Callable[[], dict[str, Any]] | None = None,
    zerotier_status_sync: Callable[[], dict[str, Any]] | None = None,
    ngrok_status_sync: Callable[[], dict[str, Any]] | None = None,
    bore_status_sync: Callable[[], dict[str, Any]] | None = None,
    priority: tuple[str, ...] | None = None,
    port: int = 8765,
) -> dict[str, Any]:
    """Return a snapshot of every provider plus a suggested active endpoint.

    ``port`` (v4.1.0) is used to build the ZeroTier ``http://<ip>:<port>``
    URL — defaults to the bridge's canonical 8765 so existing callers
    keep working unchanged.

    ``ngrok_status_sync`` (v4.33.0) is optional -- callers that predate
    the fourth-transport wiring can omit it and ngrok will report
    ``available: False`` in the snapshot.

    ``bore_status_sync`` (v4.47.0) is optional -- same back-compat
    story as ngrok. When omitted, bore reports ``available: False``.
    """
    order = priority or _priority_from_env()

    snapshots: dict[str, dict[str, Any]] = {
        "tailscale": _tailscale_snapshot(sys_funnel_status_sync),
        "cloudflared": _cloudflared_snapshot(cloudflared_status_sync),
        "zerotier": _zerotier_snapshot(zerotier_status_sync, port=port),
        "ngrok": _ngrok_snapshot(ngrok_status_sync),
        "bore": _bore_snapshot(bore_status_sync),
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
    ngrok_status_sync: Callable[[], dict[str, Any]] | None = None,
    bore_status_sync: Callable[[], dict[str, Any]] | None = None,
    priority: tuple[str, ...] | None = None,
    port: int = 8765,
) -> dict[str, Any]:
    """Return only the currently active endpoint (or an empty object)."""
    snap = tunnels_status(
        sys_funnel_status_sync=sys_funnel_status_sync,
        cloudflared_status_sync=cloudflared_status_sync,
        zerotier_status_sync=zerotier_status_sync,
        ngrok_status_sync=ngrok_status_sync,
        bore_status_sync=bore_status_sync,
        priority=priority,
        port=port,
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

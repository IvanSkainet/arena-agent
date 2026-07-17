"""Auto-detect a suitable bind address (v4.1.0).

The default ``127.0.0.1`` bind is correct when the bridge is only
consumed from the same box, but silently breaks the "agent talks
through ZeroTier / Tailscale to the bridge on another machine" use
case that motivates having those overlays in the first place. When
the operator asks for auto-bind (either via ``--bind auto`` or by
leaving the default unchanged AND setting ``ARENA_AUTO_BIND=1`` in
env), this module inspects the running network to decide whether
to widen the bind to ``0.0.0.0``.

The decision is intentionally conservative:

* An active Tailscale or ZeroTier interface counts as "operator
  meant to expose this bridge on an overlay" -- widen to 0.0.0.0.
* A LAN-only interface (eth0/wlp*/enp*) does NOT trigger widening
  by itself; those often carry untrusted traffic, and the operator
  should say ``--bind 0.0.0.0`` explicitly if they want that.
* On loopback-only hosts (containers, no ZT/TS), we stay on
  127.0.0.1 -- no regression vs. earlier releases.

The chosen bind and the *reason* are both logged so the operator
can see why a value was picked and, if surprising, override with
an explicit ``--bind``.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any


# Overlay interface name patterns that indicate the operator has
# already chosen to expose the machine on a private overlay.
_TAILSCALE_IF_PREFIXES = ("tailscale", "utun")     # tailscale0 on linux, utun* on macOS
_ZEROTIER_IF_PREFIXES = ("zt", "feth")             # zt0-zt9, feth* on macOS


def _list_interface_names() -> list[str]:
    """Return every network interface visible to the process. Uses
    ``socket.if_nameindex`` where available (POSIX + modern Windows).
    Returns an empty list on any error -- callers treat that the same
    as "no overlays detected" (fall back to 127.0.0.1)."""
    try:
        import socket
        return [name for _idx, name in socket.if_nameindex()]
    except Exception:
        return []


def _has_overlay(names: list[str], prefixes: tuple[str, ...]) -> str | None:
    for n in names:
        low = n.lower()
        for p in prefixes:
            if low.startswith(p):
                return n
    return None


def resolve_bind(
    requested: str,
    *,
    log_info: Callable[..., None] | None = None,
    zerotier_status_sync: Callable[[], dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Return ``(bind_address, reason)``.

    ``requested`` values:

    * ``"auto"`` — always run the detection.
    * literal address (``"127.0.0.1"``, ``"0.0.0.0"``, ``"10.5.1.2"``, …)
      — returned unchanged; reason is ``"explicit"``.
    * ``"127.0.0.1"`` with ``ARENA_AUTO_BIND=1`` env → treated like
      ``"auto"`` (opt-in for operators who don't want to change
      command lines).
    """
    # Explicit non-loopback address: honour it verbatim.
    if requested and requested not in ("auto", "127.0.0.1"):
        return requested, "explicit"

    # Auto mode? Either explicit "auto" or env opt-in on default.
    env_optin = os.environ.get("ARENA_AUTO_BIND", "").strip().lower() in ("1", "true", "yes", "on")
    auto_mode = requested == "auto" or (requested == "127.0.0.1" and env_optin)
    if not auto_mode:
        # Preserve the pre-v4.1.0 default: loopback-only.
        return requested or "127.0.0.1", "default loopback"

    names = _list_interface_names()
    ts = _has_overlay(names, _TAILSCALE_IF_PREFIXES)
    zt = _has_overlay(names, _ZEROTIER_IF_PREFIXES)

    if ts or zt:
        parts = []
        if ts:
            parts.append(f"Tailscale ({ts})")
        if zt:
            parts.append(f"ZeroTier ({zt})")
        reason = "overlay detected: " + ", ".join(parts) + " → binding 0.0.0.0"
        if log_info:
            try:
                log_info("[auto-bind] %s", reason)
            except Exception:
                pass
        return "0.0.0.0", reason  # nosec B104 -- 0.0.0.0 bind is deliberate: chosen after overlay-interface detection (see log_info above); tightening to a specific interface is the operator opt-in

    reason = "no overlay interface found; staying on 127.0.0.1"
    if log_info:
        try:
            log_info("[auto-bind] %s", reason)
        except Exception:
            pass
    return "127.0.0.1", reason

"""Unified autostart persistence across every transport (v4.38.0).

Generalises the v4.22.1 cloudflared_autostart pattern to every
transport that has a start/stop verb (tailscale, cloudflared,
ngrok). ZeroTier deliberately excluded -- ZT membership is
long-lived across bridge restarts and has no per-bridge
start/stop, so an autostart marker would be meaningless.

Design (identical shape per transport):

* Marker file at ``ROOT_AGENT/.<transport>_autostart`` — same
  path convention v4.22.1 established for cloudflared. Existing
  cloudflared marker keeps working: ``arena/admin/cloudflared_autostart.py``
  is now a thin re-export wrapper around this module for
  backward compat.
* Optional env override ``ARENA_<TRANSPORT>_AUTOSTART`` (case-
  insensitive truthy: ``1``/``true``/``yes``/``on``).
* Enabled = env truthy OR marker file exists.
* Marker payload: ``{"marked_at":<epoch>, "port":<int>,
  "version":1}``. Atomic write via .tmp+rename so a crash
  mid-write cannot leave a truncated marker.

Registered transports:

    TRANSPORTS = ("tailscale", "cloudflared", "ngrok")

Callers can iterate this list to render UI (per-transport
autostart checkbox) or drive lifecycle hooks (start each in
turn on bridge boot). ZeroTier absent by design.

Public API::

    is_enabled(transport, root_agent) -> bool
    enable(transport, root_agent, *, port) -> Path      # writes marker
    disable(transport, root_agent) -> bool              # removes marker
    state_snapshot(root_agent) -> dict[str, dict]       # for /v1/autostart
    marker_path(transport, root_agent) -> Path          # diagnostics

The heavy start-verb call still lives in each transport's
own module (cloudflared_action / ngrok_action /
tailscale_funnel_action). This module only decides *whether*
each one should fire on boot, and persists that decision.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


# Transports that actually have a start/stop verb. ZeroTier
# absent by design (see module docstring).
TRANSPORTS: tuple[str, ...] = ("tailscale", "cloudflared", "ngrok")


def _marker_filename(transport: str) -> str:
    return f".{transport}_autostart"


def _env_var(transport: str) -> str:
    return f"ARENA_{transport.upper()}_AUTOSTART"


def marker_path(transport: str, root_agent: Path | str) -> Path:
    """Return the on-disk marker path for a transport. Relative
    to ``root_agent`` so it moves with the install and never
    leaks to /tmp (v4.22.1 discipline)."""
    if transport not in TRANSPORTS:
        raise ValueError(
            f"unknown transport {transport!r}; "
            f"expected one of {TRANSPORTS}"
        )
    return Path(root_agent).expanduser() / _marker_filename(transport)


def is_env_enabled(transport: str) -> bool:
    """``ARENA_<TRANSPORT>_AUTOSTART`` in a truthy shape.

    Truthy values (case-insensitive): ``1``, ``true``, ``yes``,
    ``on``. Anything else — including empty string — is False.
    """
    val = os.environ.get(_env_var(transport), "").strip().lower()
    return val in ("1", "true", "yes", "on")


def is_enabled(transport: str, root_agent: Path | str) -> bool:
    """Return True when the persistent marker exists OR the env
    var is set."""
    if is_env_enabled(transport):
        return True
    return marker_path(transport, root_agent).exists()


def enable(transport: str, root_agent: Path | str, *, port: int) -> Path:
    """Write the marker so the next bridge boot autostarts this
    transport. Idempotent — overwrites an existing marker with
    a fresh timestamp/port so operators can grep the file to
    see when the tunnel was last touched.

    Atomic write via .tmp + rename so a crash mid-write cannot
    leave a truncated marker that fails to parse next boot.
    """
    path = marker_path(transport, root_agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "marked_at": int(time.time()),
        "port": int(port),
        "version": 1,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)
    return path


def disable(transport: str, root_agent: Path | str) -> bool:
    """Remove the marker. Returns True when a marker was
    actually removed, False when nothing was there -- same
    idempotent semantics as ``rm -f``.

    NB: does not clear the ``ARENA_<TRANSPORT>_AUTOSTART`` env
    variable. If an operator sets both, they must unset the env
    themselves (usually by editing the systemd service unit).
    We report the env-override situation in ``state_snapshot``
    so the UI can call it out.
    """
    path = marker_path(transport, root_agent)
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def state_snapshot(root_agent: Path | str) -> dict:
    """Serializable snapshot of autostart state for every
    registered transport. Consumed by ``GET /v1/autostart``.

    Shape::

        {
          "transports": {
            "tailscale":   {"enabled": true,  "marker": true, "env_override": false, "marker_path": "..."},
            "cloudflared": {"enabled": true,  "marker": true, "env_override": false, "marker_path": "..."},
            "ngrok":       {"enabled": false, "marker": false, "env_override": false, "marker_path": "..."}
          },
          "registered": ["tailscale", "cloudflared", "ngrok"]
        }

    ``env_override`` = the env var is truthy. When true, the UI
    should render the checkbox as forced-on with a tooltip
    explaining that only editing the service unit can turn it
    off.
    """
    transports: dict[str, dict] = {}
    for t in TRANSPORTS:
        path = marker_path(t, root_agent)
        env_override = is_env_enabled(t)
        marker = path.exists()
        transports[t] = {
            "enabled": env_override or marker,
            "marker": marker,
            "env_override": env_override,
            "marker_path": str(path),
        }
    return {
        "transports": transports,
        "registered": list(TRANSPORTS),
    }

"""cloudflared autostart persistence (v4.22.1).

Problem statement (from the v4.22.0 live-smoke session): every
time ``arena-bridge.service`` is restarted, the child ``cloudflared``
process is killed with the parent and the ``trycloudflare.com``
URL is lost until someone manually POSTs ``/v1/cloudflared/tunnel/start``.
That means ``/v1/agent/config`` — and therefore ``agentctl bridge
best`` — never sees the third transport unless a human is watching
the restart.

Design:

* When the user starts cloudflared *and* the start call succeeded,
  drop a small marker file in ``ROOT_AGENT/.cloudflared_autostart``.
* When they stop it, remove that marker.
* On process startup, the lifecycle hook checks the marker (and an
  optional ``ARENA_CLOUDFLARED_AUTOSTART`` env variable) and, if
  either signal is set, kicks off ``/v1/cloudflared/tunnel/start``
  in the background — same code path as a user call.
* Autostart is *opt-in*: a fresh install with the marker absent
  and the env unset behaves exactly like v4.22.0.
* The marker file contains a single JSON object with the timestamp
  of the last successful start plus the port. Not consumed by the
  autostart logic (which only cares if the file exists) but useful
  for diagnostics.

The whole thing is deliberately tiny — one dataclass, three
functions, no threads, no state cache. The heavy lifting still
lives in ``arena/admin/cloudflared.py``; this module just decides
*whether* to call it on boot.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MARKER_FILENAME = ".cloudflared_autostart"
ENV_VAR = "ARENA_CLOUDFLARED_AUTOSTART"


def marker_path(root_agent: Path | str) -> Path:
    """Return the on-disk marker path. Relative to ``root_agent``
    so it moves with the install and never leaks to /tmp."""
    return Path(root_agent).expanduser() / MARKER_FILENAME


def is_env_enabled() -> bool:
    """``ARENA_CLOUDFLARED_AUTOSTART`` in a truthy shape.

    Truthy values (case-insensitive): ``1``, ``true``, ``yes``,
    ``on``. Anything else — including empty string — is False.
    """
    val = os.environ.get(ENV_VAR, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def should_autostart(root_agent: Path | str) -> bool:
    """Return True when the persistent marker exists OR the env
    var is set. This is what the lifecycle hook consults."""
    if is_env_enabled():
        return True
    return marker_path(root_agent).exists()


def mark_autostart(root_agent: Path | str, *, port: int) -> Path:
    """Write the marker so the next process boot autostarts
    cloudflared. Idempotent — overwrites an existing marker with
    a fresh timestamp/port so operators can grep the file to see
    when the tunnel was last touched.
    """
    path = marker_path(root_agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "marked_at": int(time.time()),
        "port": int(port),
        "version": 1,
    }
    # Atomic write via tmp+rename so a crash mid-write cannot leave
    # a truncated marker that fails to parse next boot.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)
    return path


def unmark_autostart(root_agent: Path | str) -> bool:
    """Remove the marker. Returns True when a marker was actually
    removed, False when nothing was there — same idempotent
    semantics as ``rm -f``."""
    path = marker_path(root_agent)
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


@dataclass(frozen=True)
class AutostartOutcome:
    """Result of one autostart attempt. Purely informational —
    the lifecycle hook logs it and moves on."""
    attempted: bool
    ok: bool
    url: str
    reason: str
    duration_sec: float


def run_autostart(
    *,
    root_agent: Path | str,
    port: int,
    cloudflared_funnel_action_fn: Callable[..., dict[str, Any]],
    subprocess_kwargs_fn: Callable[[], dict[str, Any]],
) -> AutostartOutcome:
    """Perform the autostart if either signal is present.

    Same code path as ``POST /v1/cloudflared/tunnel/start``, so if
    the manual start works, the autostart works too. Returns an
    ``AutostartOutcome`` describing what happened.

    Safe to call unconditionally — if neither the marker nor the
    env var is set, this returns ``attempted=False`` and does
    nothing else. That means the lifecycle hook doesn't need to
    guard the call itself.
    """
    if not should_autostart(root_agent):
        return AutostartOutcome(attempted=False, ok=False, url="",
                                reason="no marker, env unset", duration_sec=0.0)
    t0 = time.monotonic()
    try:
        result = cloudflared_funnel_action_fn(
            "start", port,
            root_agent=Path(root_agent).expanduser(),
            subprocess_kwargs=subprocess_kwargs_fn,
        )
    except Exception as e:  # noqa: BLE001 -- swallow so bridge boots
        return AutostartOutcome(
            attempted=True, ok=False, url="",
            reason=f"start call raised: {type(e).__name__}: {str(e)[:200]}",
            duration_sec=round(time.monotonic() - t0, 3),
        )
    ok = bool(result.get("ok"))
    return AutostartOutcome(
        attempted=True,
        ok=ok,
        url=str(result.get("url", "")),
        reason=("started" if ok else str(result.get("error", "unknown"))[:200]),
        duration_sec=round(time.monotonic() - t0, 3),
    )

"""cloudflared autostart persistence -- backward-compat wrapper.

Historical (v4.22.1) this module owned the marker-file logic
directly. As of v4.38.0 the logic is generalised in
``arena/admin/autostart.py`` (which supports all transports
with a start/stop verb). This file remains as a back-compat
surface so:

* ``from arena.admin.cloudflared_autostart import mark_autostart``
  keeps working -- the wiring in ``arena/admin/handlers.py``
  and ``arena/wiring/app_lifecycle.py`` (v4.22.1) still uses
  these exact names.
* The v4.22.1 test suite ``tests/test_cloudflared_autostart.py``
  keeps passing verbatim.

Every function here is a thin proxy around the unified module
with the transport pre-bound to ``"cloudflared"``.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.admin import autostart as _unified


# Re-exported so callers that reach for the constants keep
# finding them at the historical location.
MARKER_FILENAME = ".cloudflared_autostart"
ENV_VAR = "ARENA_CLOUDFLARED_AUTOSTART"


def marker_path(root_agent: Path | str) -> Path:
    """cloudflared marker path. Delegates to the unified module."""
    return _unified.marker_path("cloudflared", root_agent)


def is_env_enabled() -> bool:
    """``ARENA_CLOUDFLARED_AUTOSTART`` in a truthy shape."""
    return _unified.is_env_enabled("cloudflared")


def should_autostart(root_agent: Path | str) -> bool:
    """Return True when the persistent marker exists OR the env
    var is set."""
    return _unified.is_enabled("cloudflared", root_agent)


def mark_autostart(root_agent: Path | str, *, port: int) -> Path:
    """Persist the autostart intent for cloudflared."""
    return _unified.enable("cloudflared", root_agent, port=port)


def unmark_autostart(root_agent: Path | str) -> bool:
    """Remove the cloudflared marker. Idempotent."""
    return _unified.disable("cloudflared", root_agent)


@dataclass(frozen=True)
class AutostartOutcome:
    """Result of one autostart attempt."""
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
    """Perform the cloudflared autostart if either signal is
    present. Identical semantics to the v4.22.1 version.
    """
    if not should_autostart(root_agent):
        return AutostartOutcome(attempted=False, ok=False, url="",
                                reason="no marker, env unset",
                                duration_sec=0.0)
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

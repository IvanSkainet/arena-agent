"""The exec profile currently in force, readable from anywhere.

`cfg["profile"]` lives in the aiohttp application and is reachable from
handlers that get a `request`. The mobile shell layer does not: it is
called through an executor, several frames from any request object, and
so it had no way to ask. The result was a phone allowlist that ignored
`owner-shell` entirely -- the operator unlocked the desktop and the
phone stayed locked, with no way to reach the setting.

This module is that missing wire. The bridge publishes the live config
once at startup; anything that needs the profile reads it here.

Deliberately a module-level reference rather than a copy: the Dashboard
switch mutates `cfg["profile"]` in place, and a snapshot taken at
startup would report the old value forever -- which is exactly the bug
this exists to fix, moved one layer down.
"""
from __future__ import annotations

from typing import Any

# The live config dict, published by the bridge at startup. None until
# then (imports, tests, CLI helpers that never start a server).
_CONFIG: dict[str, Any] | None = None

# What to answer when nothing has been published. Fails CLOSED: an
# unknown profile must never read as "unlocked", or an import ordering
# change would silently widen every phone.
DEFAULT_PROFILE = "cautious"


def publish(cfg: dict[str, Any]) -> None:
    """Register the live config. Called once, from bridge startup."""
    global _CONFIG
    _CONFIG = cfg


def current_profile() -> str:
    """The profile in force right now, re-read on every call."""
    if _CONFIG is None:
        return DEFAULT_PROFILE
    value = _CONFIG.get("profile")
    return value if isinstance(value, str) and value else DEFAULT_PROFILE


def reset_for_tests() -> None:
    """Forget the published config. Tests only."""
    global _CONFIG
    _CONFIG = None

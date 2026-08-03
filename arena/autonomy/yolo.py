"""YOLO mode (v4.97.0) -- auto-approve everything (operator switch).

YOLO mode disables per-call approval for the agent (the bridge's equivalent of
``--dangerously-skip-permissions`` / Codex's "auto-run everything"): while it is
on, ``/v1/extension/execute`` auto-approves every tool regardless of risk, so an
autonomous agent loop is not blocked waiting for a human click.

Safety posture (this is the "nobody is responsible" switch, so it is deliberately
hard to flip and fail-safe):

* **Default OFF, in-memory only.** The flag is NOT persisted; a bridge restart
  returns to the safe state. An unattended, forgotten YOLO across restarts would
  be a full-power agent with no human in the loop -- we refuse that by design.
* **Acknowledge-to-enable.** Enabling via the API requires the exact
  ``YOLO_ACK_TOKEN`` string in the request body, so it cannot be toggled by a
  stray/automated call. The Dashboard surfaces a red confirmation that supplies
  this token on the operator's explicit click.
* **Orthogonal to the kill-switch and the posture fence.** HALT is checked
  before any approval logic, and the execution posture (``arena.autonomy.posture``)
  fences ``code.run`` regardless of YOLO. So YOLO removes the *approval* step
  only; it never removes the fence or overrides HALT.
* **Not self-enabling by the agent.** There is no MCP tool that flips YOLO, so
  the agent cannot grant itself freedom through its sanctioned tool surface.
"""
from __future__ import annotations

import threading as _threading
from typing import Any

from arena.util import utc_now

# Must be supplied verbatim in the enable request body. Mirrored by the
# Dashboard's red confirmation so a human explicitly consents.
YOLO_ACK_TOKEN = "I_ACCEPT_FULL_RESPONSIBILITY"

_yolo_lock = _threading.Lock()
_yolo_state: dict[str, Any] = {
    "enabled": False,
    "enabled_at": None,   # ISO timestamp, set while enabled
    "enabled_by": None,   # caller identity, set while enabled
}


def is_yolo() -> bool:
    """True when YOLO (auto-approve everything) is engaged."""
    with _yolo_lock:
        return bool(_yolo_state["enabled"])


def yolo_status() -> dict:
    with _yolo_lock:
        return {
            "ok": True,
            "yolo": bool(_yolo_state["enabled"]),
            "enabled_at": _yolo_state["enabled_at"],
            "enabled_by": _yolo_state["enabled_by"],
            "ack_token": YOLO_ACK_TOKEN,  # so the UI can pre-fill / show the gate
        }


def set_yolo(enabled: bool, ack: str | None = None,
             by: str | None = None) -> dict:
    """Engage or disengage YOLO. Enabling requires ``ack == YOLO_ACK_TOKEN``.

    Disabling never requires the ack (failing open on the *disable* path would
    be wrong; failing CLOSED on enable is the point)."""
    enabled = bool(enabled)
    if enabled and ack != YOLO_ACK_TOKEN:
        return {
            "ok": False,
            "error": "yolo_ack_required",
            "required_ack": YOLO_ACK_TOKEN,
            "message": (
                "Enabling YOLO auto-approves EVERY tool call with no human in "
                "the loop. Re-send with ack set to the required token after an "
                "explicit human confirmation. Nobody is responsible for what "
                "the agent does while YOLO is on."),
        }
    with _yolo_lock:
        prev = _yolo_state["enabled"]
        _yolo_state["enabled"] = enabled
        if enabled:
            _yolo_state["enabled_at"] = utc_now()
            _yolo_state["enabled_by"] = by
        else:
            _yolo_state["enabled_at"] = None
            _yolo_state["enabled_by"] = None
        return {
            "ok": True,
            "yolo": enabled,
            "previous": prev,
            "enabled_at": _yolo_state["enabled_at"],
        }


__all__ = ["YOLO_ACK_TOKEN", "is_yolo", "yolo_status", "set_yolo"]

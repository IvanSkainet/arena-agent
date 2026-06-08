"""Desktop control-lease state (v2.9.0).

Global state for the agent control lease: lets the user pause/revoke desktop
automation from the local environment (hotkey, tray, or API). The state dict and
lock are module-level singletons shared by every importer.

Re-exported by ``unified_bridge.py`` for backward compatibility.
"""
from __future__ import annotations

import threading as _threading

from arena.util import utc_now

_control_state = {
    "status": "active",          # "active" | "paused" | "revoked"
    "reason": None,              # optional reason string
    "paused_at": None,           # ISO timestamp when paused
    "revoked_at": None,          # ISO timestamp when revoked
    "last_agent_input_at": None, # ISO timestamp of last agent action
    "last_user_input_at": None,  # ISO timestamp of last detected user input
    "session_id": None,          # optional session identifier
}
_control_lock = _threading.Lock()


def _control_check() -> dict | None:
    """Check if agent control is currently allowed.
    Returns None if OK, or an error dict if paused/revoked."""
    with _control_lock:
        st = _control_state["status"]
        if st == "active":
            return None
        elif st == "paused":
            return {"ok": False, "error": "control_paused",
                    "message": "Agent desktop control is paused by user",
                    "status": st, "reason": _control_state["reason"]}
        elif st == "revoked":
            return {"ok": False, "error": "control_revoked",
                    "message": "User revoked desktop control",
                    "status": st, "reason": _control_state["reason"]}
        return None


def _control_record_agent_action():
    """Record that the agent just performed a desktop action."""
    with _control_lock:
        _control_state["last_agent_input_at"] = utc_now()

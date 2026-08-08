"""Desktop control-lease state (v2.9.0).

Global state for the agent control lease: lets the user pause/revoke desktop
automation from the local environment (hotkey, tray, or API). The state dict and
lock are module-level singletons shared by every importer.

Re-exported by ``unified_bridge.py`` for backward compatibility.
"""
from __future__ import annotations

import threading as _threading
from typing import Any

from arena.util import utc_now

_control_state: dict[str, Any] = {
    "status": "active",          # "active" | "paused" | "revoked"
    "reason": None,              # optional reason string
    "paused_at": None,           # ISO timestamp when paused
    "revoked_at": None,          # ISO timestamp when revoked
    "last_agent_input_at": None, # ISO timestamp of last agent action
    "last_user_input_at": None,  # ISO timestamp of last detected user input
    "session_id": None,          # optional session identifier
    # v4.97.0: full agent stop (kill-switch), orthogonal to the desktop
    # control lease (status paused/revoked). When True, every non-read-only
    # agent action is blocked across all entry points; read-only calls and
    # the /v1/control/* plane stay available so a human can resume. Defaults
    # to False so an unconfigured bridge behaves exactly as before.
    "agent_halted": False,
    "halted_at": None,
    "halted_reason": None,
}
_control_lock = _threading.Lock()


def is_halted() -> bool:
    """True when the agent kill-switch is engaged.

    v4.169.5: `/v1/self` imported a `control_status` that does not exist
    in this module. The import sat inside a bare `except Exception`, so
    it failed silently on every call and the self-description reported
    `halt: inactive` while the bridge was genuinely halted -- verified
    live: `/v1/control/status` said `agent_halted: true` and `/v1/self`
    said `false` at the same moment.

    Pyright had been reporting it as `reportAttributeAccessIssue` the
    whole time. Nobody was reading Pyright.

    An agent that has been stopped and is told it has not been stopped
    is the worst possible failure of a self-description: it will keep
    trying, blame the tools, and report the wrong thing to the operator.
    """
    with _control_lock:
        return bool(_control_state["agent_halted"])


def _control_check() -> dict | None:
    """Check if agent control is currently allowed.
    Returns None if OK, or an error dict if paused/revoked."""
    with _control_lock:
        # v4.97.0: a full stop overrides the desktop lease -- @controlled
        # (desktop input) consults this function, so halting also freezes
        # desktop actuation, not just tool-bus actions.
        if _control_state["agent_halted"]:
            return {"ok": False, "error": "agent_halted",
                    "message": "Agent is HALTED (full stop). All non-read-only "
                               "actions are blocked. Resume via "
                               "/v1/control/unhalt.",
                    "status": "halted",
                    "reason": _control_state["halted_reason"]}
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


# ---------------------------------------------------------------------------
# v4.97.0: full agent stop (kill-switch)
# ---------------------------------------------------------------------------

# Read-only tools stay callable while halted so the agent / observer can still
# see state; everything else (medium / dangerous / unknown) is blocked.
# ``mcp.ext_call`` is classified ``safe`` (trust is decided at ``mcp.add``) but
# it mutates external state, so it is ALSO blocked under a full stop -- we fail
# closed rather than trust an external server to be a no-op.
_SAFE_BUT_BLOCKS_WHEN_HALTED = frozenset({"mcp.ext_call"})


def _agent_halt_reason() -> dict | None:
    """Error dict when the full agent stop is engaged, else ``None``."""
    with _control_lock:
        if not _control_state["agent_halted"]:
            return None
        return {"ok": False, "error": "agent_halted",
                "message": "Agent is HALTED (full stop). All non-read-only "
                           "actions are blocked. Resume via "
                           "/v1/control/unhalt.",
                "status": "halted",
                "reason": _control_state["halted_reason"]}


def _agent_halt_block_for_tool(name: str) -> dict | None:
    """The single chokepoint decision used by the MCP tool dispatcher.

    Returns a block error when the full stop is engaged AND ``name`` is not a
    read-only tool; ``None`` otherwise. Kept as a pure-ish helper (only the
    global halt flag + the policy risk table) so it is unit-testable without
    constructing the full tool runtime."""
    reason = _agent_halt_reason()
    if reason is None:
        return None
    from arena.extension_bridge.policy import classify_tool_risk  # lazy: no cycle
    risk = classify_tool_risk(str(name or "").strip())
    if risk == "safe" and name not in _SAFE_BUT_BLOCKS_WHEN_HALTED:
        return None
    block = dict(reason)
    block["message"] = (
        f"BLOCKED while agent is halted: tool '{name}' is not read-only "
        f"(risk={risk}). Resume via /v1/control/unhalt to re-enable actuation.")
    block["tool"] = name
    block["risk"] = risk
    return block


def _control_halt(reason: str | None = None) -> dict:
    """Engage the full agent stop. Idempotent."""
    with _control_lock:
        _control_state["agent_halted"] = True
        _control_state["halted_at"] = utc_now()
        _control_state["halted_reason"] = reason or "User halted the agent"
        return {"ok": True, "agent_halted": True,
                "halted_at": _control_state["halted_at"],
                "reason": _control_state["halted_reason"]}


def _control_unhalt() -> dict:
    """Disengage the full agent stop. Idempotent."""
    with _control_lock:
        was = _control_state["agent_halted"]
        _control_state["agent_halted"] = False
        _control_state["halted_at"] = None
        _control_state["halted_reason"] = None
        return {"ok": True, "agent_halted": False, "was_halted": was}

"""v4.97.0 -- full agent stop (kill-switch) core.

Tests the control-module decision logic that the MCP tool dispatcher uses as
its single chokepoint. The flag is a process-global singleton, so the autouse
fixture snapshots + restores ``_control_state`` to prevent a halted flag from
leaking into the rest of the suite (which would block every mutating tool).
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena import control as ctrl  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_control_state():
    snap = copy.deepcopy(ctrl._control_state)
    yield
    ctrl._control_state.clear()
    ctrl._control_state.update(snap)


# ---------------------------------------------------------------------------
# default / transitions
# ---------------------------------------------------------------------------

def test_default_not_halted():
    assert ctrl._agent_halt_reason() is None
    assert ctrl._control_check() is None  # status active, not halted


def test_halt_then_unhalt_transitions():
    res = ctrl._control_halt("test stop")
    assert res["ok"] and res["agent_halted"] is True and res["reason"] == "test stop"
    reason = ctrl._agent_halt_reason()
    assert reason is not None and reason["error"] == "agent_halted"
    assert reason["status"] == "halted" and reason["reason"] == "test stop"

    res2 = ctrl._control_unhalt()
    assert res2["ok"] and res2["agent_halted"] is False and res2["was_halted"] is True
    assert ctrl._agent_halt_reason() is None


def test_halt_is_idempotent_and_unhalt_when_not_halted():
    ctrl._control_halt()
    ctrl._control_halt("again")
    assert ctrl._control_state["agent_halted"] is True
    assert ctrl._control_unhalt()["was_halted"] is True
    assert ctrl._control_unhalt()["was_halted"] is False  # already clear


# ---------------------------------------------------------------------------
# _control_check: halted overrides the desktop lease
# ---------------------------------------------------------------------------

def test_control_check_halted_overrides_active():
    ctrl._control_halt()
    chk = ctrl._control_check()
    assert chk and chk["error"] == "agent_halted"


def test_control_check_halted_overrides_paused():
    # desktop lease paused, THEN full stop engaged -> halted wins.
    with ctrl._control_lock:
        ctrl._control_state["status"] = "paused"
    ctrl._control_halt()
    chk = ctrl._control_check()
    assert chk and chk["error"] == "agent_halted"  # not control_paused


def test_control_check_paused_still_works_when_not_halted():
    with ctrl._control_lock:
        ctrl._control_state["status"] = "paused"
    chk = ctrl._control_check()
    assert chk and chk["error"] == "control_paused"


# ---------------------------------------------------------------------------
# chokepoint decision: read-only passes, mutating blocked, fail-closed
# ---------------------------------------------------------------------------

def test_block_for_tool_none_when_not_halted():
    assert ctrl._agent_halt_block_for_tool("exec.exec") is None
    assert ctrl._agent_halt_block_for_tool("fs.read") is None


@pytest.mark.parametrize("read_only_tool", [
    "fs.read", "fs.list", "fs.tree", "fs.view", "fs.grep",
    "sys.status", "mobile.info", "mobile.screenshot",
    "custom.list",            # safe authored wrapper
    "mcp.ext_servers",        # safe, read-only
])
def test_read_only_tools_allowed_while_halted(read_only_tool):
    ctrl._control_halt()
    assert ctrl._agent_halt_block_for_tool(read_only_tool) is None


@pytest.mark.parametrize("mutating_tool", [
    "exec.exec", "fs.write", "fs.create", "fs.edit",
    "desktop.click", "mobile.shell", "mobile.tap",
    "custom.create",            # medium authored-management
    "custom.remove",
    "mcp.add",
])
def test_mutating_tools_blocked_while_halted(mutating_tool):
    ctrl._control_halt()
    block = ctrl._agent_halt_block_for_tool(mutating_tool)
    assert block is not None
    assert block["error"] == "agent_halted"
    assert block["tool"] == mutating_tool
    assert block["risk"] in ("medium", "dangerous")


def test_ext_call_blocked_while_halted_even_though_safe():
    # mcp.ext_call is policy-safe (trust at mcp.add) but mutates external
    # state -> a full stop must block it (fail closed).
    ctrl._control_halt()
    block = ctrl._agent_halt_block_for_tool("mcp.ext_call")
    assert block is not None and block["risk"] == "safe"


@pytest.mark.parametrize("non_readonly_tool", [
    "totally.made_up",   # genuinely unknown -> fail closed
    "exec.ping",         # harmless but policy-unknown -> fail closed too
])
def test_unknown_or_alias_tool_fail_closed_while_halted(non_readonly_tool):
    ctrl._control_halt()
    block = ctrl._agent_halt_block_for_tool(non_readonly_tool)
    assert block is not None and block["risk"] == "unknown"

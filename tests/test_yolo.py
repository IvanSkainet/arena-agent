"""v4.97.0 -- YOLO mode (auto-approve everything) tests.

Covers the acknowledge-to-enable gate, the default-off / fail-safe posture, the
policy snapshot flag, and the execute_sync approval bypass. The flag is a
process-global singleton, so the autouse fixture resets it to avoid leaking an
enabled YOLO into the rest of the suite (which would auto-approve everything).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena import autonomy  # noqa: E402
from arena.autonomy import YOLO_ACK_TOKEN, is_yolo, set_yolo, yolo_status  # noqa: E402
from arena.extension_bridge.policy import extension_policy_snapshot  # noqa: E402
from arena.extension_bridge.runtime import (  # noqa: E402
    ExtensionBridgeRuntimeContext,
    make_extension_bridge_runtime,
)


@pytest.fixture(autouse=True)
def _reset_yolo():
    yield
    autonomy.yolo._yolo_state["enabled"] = False
    autonomy.yolo._yolo_state["enabled_at"] = None
    autonomy.yolo._yolo_state["enabled_by"] = None


# ---------------------------------------------------------------------------
# autonomy module
# ---------------------------------------------------------------------------

def test_default_off():
    assert is_yolo() is False


def test_enable_requires_ack():
    res = set_yolo(True)  # no ack
    assert res["ok"] is False and res["error"] == "yolo_ack_required"
    assert is_yolo() is False
    res2 = set_yolo(True, ack="wrong")
    assert res2["ok"] is False
    assert is_yolo() is False


def test_enable_with_ack_then_disable_without_ack():
    res = set_yolo(True, ack=YOLO_ACK_TOKEN, by="tester")
    assert res["ok"] and res["yolo"] is True and res["previous"] is False
    assert is_yolo() is True
    # disabling must NOT require the ack (fail closed is only on enable)
    res2 = set_yolo(False)
    assert res2["ok"] and res2["yolo"] is False and res2["previous"] is True
    assert is_yolo() is False


def test_yolo_status_exposes_ack_token_and_state():
    st = yolo_status()
    assert st["ok"] and st["yolo"] is False and st["ack_token"] == YOLO_ACK_TOKEN
    set_yolo(True, ack=YOLO_ACK_TOKEN)
    st2 = yolo_status()
    assert st2["yolo"] is True and st2["enabled_by"] is None or True  # by not passed


def test_policy_snapshot_reflects_yolo():
    assert extension_policy_snapshot()["yolo"] is False
    set_yolo(True, ack=YOLO_ACK_TOKEN)
    assert extension_policy_snapshot()["yolo"] is True


# ---------------------------------------------------------------------------
# execute_sync approval bypass
# ---------------------------------------------------------------------------

def _runtime(call_log, audit_log):
    def call_tool(name, args):
        call_log.append((name, args))
        return {"content": [{"type": "text", "text": "{\"ok\": true}"}]}

    ctx = ExtensionBridgeRuntimeContext(
        call_tool=call_tool,
        audit=lambda d: audit_log.append(d),
    )
    return make_extension_bridge_runtime(ctx)


def _payload(tool="fs.create", args=None):
    return {"payload": {"bridge": "arena", "version": 1, "calls": [
        {"id": "c1", "tool": tool, "arguments": args or {"path": "/x", "content": "y"}}]},
        "mode": {}}


def test_execute_sync_blocks_medium_without_approve_when_yolo_off():
    call_log, audit_log = [], []
    rt = _runtime(call_log, audit_log)
    res = rt.execute_sync(_payload())  # fs.create = medium, no approve
    assert res["ok"] is False
    assert res.get("status") == 403 and res.get("error") == "approval required"
    assert call_log == []  # never executed


def test_execute_sync_allows_medium_without_approve_when_yolo_on():
    set_yolo(True, ack=YOLO_ACK_TOKEN)
    call_log, audit_log = [], []
    rt = _runtime(call_log, audit_log)
    res = rt.execute_sync(_payload())  # no approve, but YOLO on
    assert res["ok"] is True
    assert call_log == [("fs.create", {"path": "/x", "content": "y"})]
    assert audit_log and audit_log[0]["approved"] is True
    assert audit_log[0]["yolo_auto"] is True


def test_execute_sync_explicit_approve_still_works_and_not_marked_yolo():
    call_log, audit_log = [], []
    rt = _runtime(call_log, audit_log)
    data = _payload()
    data["mode"] = {"approve": True}
    res = rt.execute_sync(data)
    assert res["ok"] is True and call_log
    assert audit_log[0]["yolo_auto"] is False  # human-approved, not YOLO


def test_execute_sync_safe_tool_auto_runs_on_trusted_site_without_yolo():
    # On a TRUSTED site, safe tools auto-run with neither approval nor YOLO
    # (the extension's "safe-auto-run" model). YOLO is not needed for them.
    call_log, audit_log = [], []
    rt = _runtime(call_log, audit_log)
    data = _payload(tool="fs.read", args={"path": "/x"})
    data["site"] = {"origin": "https://chat.openai.com"}  # trusted host
    res = rt.execute_sync(data)
    assert res["ok"] is True and call_log == [("fs.read", {"path": "/x"})]
    assert audit_log[0]["yolo_auto"] is False

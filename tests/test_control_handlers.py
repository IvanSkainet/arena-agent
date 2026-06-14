"""Desktop control lease handler extraction tests."""
import asyncio
import threading
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.control_handlers import make_control_lease_handlers  # noqa: E402
from arena.handler_context import ControlLeaseHandlerContext  # noqa: E402


class _Request:
    def __init__(self, payload=None):
        self._payload = payload

    async def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _state():
    return {
        "status": "active",
        "reason": None,
        "paused_at": None,
        "revoked_at": None,
        "last_agent_input_at": None,
        "last_user_input_at": None,
        "session_id": None,
    }


def _ctx(state=None) -> ControlLeaseHandlerContext:
    return ControlLeaseHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        control_state=state or _state(),
        control_lock=threading.Lock(),
        utc_now=lambda: "now",
        log_info=lambda *args, **kwargs: None,
        log_warning=lambda *args, **kwargs: None,
    )


def _json(response):
    return ub.json.loads(response.text)


def test_control_handlers_factory_outputs():
    handlers = make_control_lease_handlers(_ctx())
    assert callable(handlers.status)
    assert callable(handlers.pause)
    assert callable(handlers.resume)
    assert callable(handlers.revoke)


def test_control_routes_registered():
    app = ub.make_app({
        "token": "test",
        "profile": "owner-shell",
        "root": Path("/tmp"),
        "active_exec": 0,
        "max_concurrent": 3,
        "audit": "audit",
        "timeout": 60,
        "max_timeout": 3600,
        "max_output": 2000000,
        "allow_any_cwd": False,
        "semaphore": asyncio.Semaphore(1),
    })
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/control/status") in paths
    assert ("POST", "/v1/control/pause") in paths
    assert ("POST", "/v1/control/resume") in paths
    assert ("POST", "/v1/control/revoke") in paths


def test_unified_control_handlers_bound_to_control_module():
    assert ub.handle_v1_control_status.__module__ == "arena.control_handlers"
    assert ub.handle_v1_control_pause.__module__ == "arena.control_handlers"
    assert ub.handle_v1_control_resume.__module__ == "arena.control_handlers"
    assert ub.handle_v1_control_revoke.__module__ == "arena.control_handlers"


def test_control_status_snapshot():
    state = _state()
    state["session_id"] = "s1"
    response = asyncio.run(make_control_lease_handlers(_ctx(state)).status(_Request()))
    body = _json(response)
    assert body["ok"] is True
    assert body["control"] == "active"
    assert body["session_id"] == "s1"


def test_control_pause_resume_revoke_flow():
    state = _state()
    handlers = make_control_lease_handlers(_ctx(state))

    pause = asyncio.run(handlers.pause(_Request({"reason": "unit"})))
    assert _json(pause) == {"ok": True, "control": "paused", "reason": "unit", "paused_at": "now"}
    assert state["status"] == "paused"

    resume = asyncio.run(handlers.resume(_Request()))
    assert _json(resume) == {"ok": True, "control": "active", "previous_status": "paused", "resumed_at": "now"}
    assert state["status"] == "active"

    revoke = asyncio.run(handlers.revoke(_Request({"reason": "stop"})))
    assert _json(revoke) == {"ok": True, "control": "revoked", "reason": "stop", "revoked_at": "now"}
    assert state["status"] == "revoked"


def test_control_pause_rejected_when_revoked():
    state = _state()
    state["status"] = "revoked"
    response = asyncio.run(make_control_lease_handlers(_ctx(state)).pause(_Request({"reason": "unit"})))
    body = _json(response)
    assert response.status == 409
    assert body["ok"] is False
    assert body["error"] == "control_revoked"

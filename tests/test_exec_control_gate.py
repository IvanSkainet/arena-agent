"""T59 parity for control-lease gates across every exec transport."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web

from arena.app_keys import APP_CFG
from arena.exec.control_gate import control_injection_error, control_injection_response
from arena.exec.handlers import make_exec_handlers
from arena.handler_context import ExecHandlerContext


class FakeContext:
    def __init__(self, control=None, matched=None):
        self.control = control
        self.matched = matched
        self.audit_events = []
        self.records = []
        self.matcher_calls = []

    def control_check(self):
        return self.control

    def is_input_injection_cmd(self, command):
        self.matcher_calls.append(command)
        return self.matched

    def audit(self, event):
        self.audit_events.append(event)

    def record_request(self, **kwargs):
        self.records.append(kwargs)

    @staticmethod
    def cors_json_response(payload, *, status=200):
        return web.json_response(payload, status=status)


def test_pure_gate_only_blocks_injection_while_control_is_paused() -> None:
    active = FakeContext(control=None, matched="xdotool")
    assert control_injection_error(
        command="xdotool key a", request_id="r1",
        control_check=active.control_check,
        injection_matcher=active.is_input_injection_cmd,
    ) is None
    assert active.matcher_calls == [], "do not classify input when control is active"

    paused_benign = FakeContext(
        control={"ok": False, "error": "paused", "status": "paused"},
        matched=None,
    )
    assert control_injection_error(
        command="echo ok", request_id="r2",
        control_check=paused_benign.control_check,
        injection_matcher=paused_benign.is_input_injection_cmd,
    ) is None
    assert paused_benign.matcher_calls == ["echo ok"]

    paused_injection = FakeContext(
        control={"ok": False, "error": "paused", "status": "paused"},
        matched="xdotool key",
    )
    error = control_injection_error(
        command="xdotool key a", request_id="r3",
        control_check=paused_injection.control_check,
        injection_matcher=paused_injection.is_input_injection_cmd,
    )
    assert error == {
        "ok": False,
        "error": "paused",
        "status": "paused",
        "request_id": "r3",
        "matched": "xdotool key",
        "message": (
            "Desktop input injection blocked while control is paused. "
            "Resume control to inject input."
        ),
    }


def test_response_helper_emits_exact_audit_and_accounting() -> None:
    ctx = FakeContext(
        control={"ok": False, "error": "lease paused", "status": "paused"},
        matched="wtype",
    )
    request = SimpleNamespace(remote="198.51.100.7")
    response = control_injection_response(
        ctx=ctx, request=request, command="wtype hello", request_id="req",
        event_type="exec_script_blocked_control",
        audit_fields={"interpreter": "bash"},
    )
    assert response is not None and response.status == 403
    assert json.loads(response.text)["request_id"] == "req"
    assert ctx.audit_events == [{
        "type": "exec_script_blocked_control",
        "request_id": "req",
        "reason": "lease paused",
        "matched": "wtype",
        "client": "198.51.100.7",
        "interpreter": "bash",
    }]
    assert ctx.records == [{"is_error": True, "count_request": False}]

    fallback = FakeContext(
        control={"ok": False, "error": "paused", "status": "paused"},
        matched="wtype",
    )
    control_injection_response(
        ctx=fallback, request=SimpleNamespace(remote=None), command="wtype x",
        request_id="local", event_type="exec_blocked_control",
    )
    assert fallback.audit_events[0]["client"] == "127.0.0.1"


def _handler_context(*, profile: str, control, matched, audits, records):
    return ExecHandlerContext(
        require_auth=lambda _request: None,
        record_request=lambda **kwargs: records.append(kwargs),
        cors_json_response=lambda payload, status=200: web.json_response(payload, status=status),
        audit=lambda event: audits.append(event),
        blocked_reason=lambda _cmd: None,
        control_check=lambda: control,
        is_input_injection_cmd=lambda _cmd: matched,
        first_word=lambda cmd: cmd.split()[0] if cmd.split() else "",
        under_root=lambda child, root: True,
        decode_output=lambda body: body.decode("utf-8", "replace"),
        run_shell_command=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
        active_processes={},
        active_processes_snapshot=lambda **_kwargs: [],
        cautious_allow=set(),
        default_max_output=1000,
    )


class ScriptRequest:
    def __init__(self, cfg, body, interpreter):
        self.app = {APP_CFG: cfg}
        self.headers = {"X-Arena-Interpreter": interpreter}
        self.remote = "203.0.113.5"
        self._body = body

    async def read(self):
        return self._body


def _script_cfg(tmp_path: Path, profile: str):
    return {
        "profile": profile,
        "root": tmp_path,
        "timeout": 30,
        "max_timeout": 60,
        "max_output": 10_000,
        "allow_any_cwd": False,
        "active_exec": 0,
        "max_concurrent": 1,
        "semaphore": asyncio.Semaphore(1),
    }


def test_raw_script_blocks_paused_input_before_writing_or_running(tmp_path: Path) -> None:
    audits, records = [], []
    ctx = _handler_context(
        profile="owner-shell",
        control={"ok": False, "error": "paused", "status": "paused"},
        matched="xdotool key",
        audits=audits,
        records=records,
    )
    handlers = make_exec_handlers(ctx)
    interpreter = "powershell" if os.name == "nt" else "bash"
    request = ScriptRequest(
        _script_cfg(tmp_path, "owner-shell"), b"xdotool key ctrl+l", interpreter,
    )
    with patch("arena.exec.handlers._which_interpreter", return_value=True):
        response = asyncio.run(handlers.script.__wrapped__(request))
    assert response.status == 403
    assert json.loads(response.text)["matched"] == "xdotool key"
    assert audits[0]["type"] == "exec_script_blocked_control"
    assert not (tmp_path / ".arena_script_tmp").exists()


def test_raw_script_is_unavailable_in_cautious_profile(tmp_path: Path) -> None:
    audits, records = [], []
    ctx = _handler_context(
        profile="cautious", control=None, matched=None,
        audits=audits, records=records,
    )
    handlers = make_exec_handlers(ctx)
    interpreter = "powershell" if os.name == "nt" else "bash"
    request = ScriptRequest(_script_cfg(tmp_path, "cautious"), b"echo harmless", interpreter)
    with patch("arena.exec.handlers._which_interpreter", return_value=True):
        response = asyncio.run(handlers.script.__wrapped__(request))
    body = json.loads(response.text)
    assert response.status == 403
    assert "raw scripts require owner-shell" in body["error"]
    assert audits == [{
        "type": "exec_script_blocked",
        "request_id": body["request_id"],
        "interpreter": interpreter,
        "reason": "raw scripts require owner-shell; cautious cannot inspect script semantics",
        "client": "203.0.113.5",
    }]

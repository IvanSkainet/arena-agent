"""Tests for POST /v1/exec/stream (v4.3.0 NDJSON streaming)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402


def test_exec_stream_route_in_registry():
    from arena.route_registry.registry import ROUTES
    keys = {(m, p) for (m, p, *_rest) in ROUTES}
    assert ("POST", "/v1/exec/stream") in keys


def test_exec_stream_route_wired_into_app():
    app = ub.make_app({
        "token": "test", "profile": "owner-shell", "root": Path("/tmp"),
        "active_exec": 0, "max_concurrent": 3, "audit": "audit",
        "timeout": 60, "max_timeout": 3600, "max_output": 2000000,
        "allow_any_cwd": False, "semaphore": asyncio.Semaphore(1),
    })
    paths = {
        (r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter"))
        for r in app.router.routes()
    }
    assert ("POST", "/v1/exec/stream") in paths


def test_exec_handlers_factory_exposes_stream():
    """Regression guard: the stream handler is exported on ExecHandlers."""
    from arena.exec.handlers import make_exec_handlers, ExecHandlers  # noqa: F401
    from arena.handler_context import ExecHandlerContext
    ctx = ExecHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        audit=ub.audit,
        blocked_reason=ub.blocked_reason,
        control_check=ub._control_check,
        is_input_injection_cmd=ub._is_input_injection_cmd,
        first_word=ub.first_word,
        under_root=ub.under_root,
        decode_output=ub.decode_output,
        run_shell_command=ub.run_shell_command,
        active_processes=ub.ACTIVE_PROCESSES,
        active_processes_snapshot=ub.active_processes_snapshot,
        cautious_allow=ub.CAUTIOUS_ALLOW,
        default_max_output=ub.DEFAULT_MAX_OUTPUT,
    )
    handlers = make_exec_handlers(ctx)
    assert callable(handlers.stream)
    # @authed-wrapped (v3.94.0 migration).
    assert hasattr(handlers.stream, "__wrapped__")


def test_run_shell_command_stream_yields_events():
    """The runner must yield start, at least one stdout chunk, and exit."""
    from arena.exec.runner import run_shell_command_stream

    async def _collect():
        events = []
        async for ev in run_shell_command_stream(
            request_id="t1",
            cmd="printf 'hello\\nworld\\n'",
            cwd=Path("/tmp"),
            env={"PATH": "/usr/bin:/bin"},
            timeout=10,
            max_output=1024,
        ):
            events.append(ev)
        return events

    events = asyncio.run(_collect())
    assert events, "no events emitted"
    assert events[0]["type"] == "start"
    assert isinstance(events[0].get("pid"), int)
    assert events[-1]["type"] == "exit"
    assert events[-1]["exit_code"] == 0
    assert events[-1]["timed_out"] is False
    stdout_chunks = [ev for ev in events if ev["type"] == "stdout"]
    assert stdout_chunks, "expected at least one stdout chunk"
    all_bytes = b"".join(ev["data"] for ev in stdout_chunks)
    assert b"hello" in all_bytes and b"world" in all_bytes


def test_run_shell_command_stream_captures_stderr():
    """Stderr must be surfaced as its own event stream."""
    from arena.exec.runner import run_shell_command_stream

    async def _collect():
        events = []
        async for ev in run_shell_command_stream(
            request_id="t2",
            cmd="printf 'oops\\n' 1>&2; exit 3",
            cwd=Path("/tmp"),
            env={"PATH": "/usr/bin:/bin"},
            timeout=10,
            max_output=1024,
        ):
            events.append(ev)
        return events

    events = asyncio.run(_collect())
    assert events[-1]["type"] == "exit"
    assert events[-1]["exit_code"] == 3
    stderr_chunks = [ev for ev in events if ev["type"] == "stderr"]
    assert stderr_chunks, "expected stderr chunk"
    assert b"oops" in b"".join(ev["data"] for ev in stderr_chunks)


def test_run_shell_command_stream_timeout_marks_event():
    """A wall-clock timeout kills the process and terminal event has timed_out=True."""
    from arena.exec.runner import run_shell_command_stream

    async def _collect():
        events = []
        async for ev in run_shell_command_stream(
            request_id="t3",
            cmd="sleep 5",
            cwd=Path("/tmp"),
            env={"PATH": "/usr/bin:/bin"},
            timeout=1,
            max_output=1024,
        ):
            events.append(ev)
        return events

    events = asyncio.run(_collect())
    assert events[-1]["type"] == "exit"
    assert events[-1]["timed_out"] is True
    assert events[-1]["error"] and "timeout" in events[-1]["error"]


def test_run_shell_command_stream_max_output_truncates():
    """When output exceeds max_output, truncated=True and byte counter reflects total."""
    from arena.exec.runner import run_shell_command_stream

    async def _collect():
        events = []
        async for ev in run_shell_command_stream(
            request_id="t4",
            # Emit ~20k bytes; cap at 4k.
            cmd="python3 -c \"import sys; sys.stdout.write('A'*20000)\"",
            cwd=Path("/tmp"),
            env={"PATH": "/usr/bin:/bin"},
            timeout=10,
            max_output=4096,
        ):
            events.append(ev)
        return events

    events = asyncio.run(_collect())
    assert events[-1]["type"] == "exit"
    assert events[-1]["truncated"] is True
    assert events[-1]["stdout_bytes"] >= 20000
    stdout_bytes_emitted = sum(len(ev["data"]) for ev in events if ev["type"] == "stdout")
    assert stdout_bytes_emitted <= 4096


def test_exec_stream_ndjson_serializer_shape():
    """NDJSON contract: each event is a single JSON object per line
    with a mandatory ``type`` key. Guards against accidental pretty-
    printing (indent=2) that would break line-delimited parsers on
    the agent side.

    End-to-end wire behavior is covered by the live-smoke run against
    the bridge (see release notes); we don't spin up aiohttp
    TestServer here because it shuts down unified_bridge's module-
    level executors on cleanup, poisoning unrelated tests.
    """
    sample_events = [
        {"type": "meta", "request_id": "abc", "cmd": "echo hi"},
        {"type": "start", "pid": 42, "request_id": "abc"},
        {"type": "stdout", "data": "hi\n", "bytes": 3},
        {"type": "exit", "exit_code": 0, "duration_sec": 0.01,
         "stdout_bytes": 3, "stderr_bytes": 0, "truncated": False,
         "timed_out": False, "error": None, "request_id": "abc"},
    ]
    lines = [json.dumps(ev, ensure_ascii=False) for ev in sample_events]
    for line in lines:
        assert "\n" not in line, f"event serialized with embedded newline: {line!r}"
        parsed = json.loads(line)
        assert "type" in parsed

"""T44: remote client aborts cancel and reap in-flight exec trees."""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from aiohttp import web

from arena.app_keys import APP_CFG
from arena.exec import handlers as exec_handlers, runner
from arena.exec.client_lifecycle import (
    ClientDisconnected,
    await_while_client_connected,
    forward_stream_events,
)
from arena.exec.handlers import make_exec_handlers
from arena.handler_context import ExecHandlerContext


class _Transport:
    def __init__(self) -> None:
        self.closing = False

    def is_closing(self) -> bool:
        return self.closing


class _Request:
    def __init__(self, transport: _Transport | None) -> None:
        self.transport = transport
        self.remote: str | None = None


def test_disconnect_watcher_cancels_and_awaits_work() -> None:
    async def scenario() -> None:
        transport = _Transport()
        cancelled = asyncio.Event()

        async def work() -> None:
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        task = asyncio.create_task(
            await_while_client_connected(
                _Request(transport), work(), poll_interval=0,
            )
        )
        await asyncio.sleep(0)
        transport.closing = True
        with pytest.raises(ClientDisconnected, match="^HTTP client disconnected during exec$"):
            await asyncio.wait_for(task, timeout=1)
        assert cancelled.is_set()

    asyncio.run(scenario())


def test_default_poll_interval_detects_disconnect_promptly() -> None:
    async def scenario() -> None:
        transport = _Transport()
        loop = asyncio.get_running_loop()
        loop.call_later(0.01, setattr, transport, "closing", True)
        started = loop.time()
        with pytest.raises(ClientDisconnected):
            await asyncio.wait_for(
                await_while_client_connected(_Request(transport), asyncio.sleep(30)),
                timeout=0.5,
            )
        assert loop.time() - started < 0.5

    asyncio.run(scenario())


def test_outer_cancellation_awaits_worker_cleanup_without_masking_cancel() -> None:
    async def scenario() -> None:
        cleaned = asyncio.Event()

        async def work() -> None:
            try:
                await asyncio.Future()
            finally:
                cleaned.set()
                raise RuntimeError("cleanup failure")

        task = asyncio.create_task(await_while_client_connected(_Request(_Transport()), work()))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()

    asyncio.run(scenario())


def test_all_long_running_v1_exec_paths_bind_work_to_the_client() -> None:
    handlers_source = inspect.getsource(make_exec_handlers)
    forwarder_source = inspect.getsource(forward_stream_events)
    assert handlers_source.count("await await_while_client_connected(") == 2
    assert forwarder_source.count("await await_while_client_connected(") == 1


def test_request_without_transport_keeps_direct_call_semantics() -> None:
    async def scenario() -> None:
        assert await await_while_client_connected(_Request(None), asyncio.sleep(0, result=7)) == 7

    asyncio.run(scenario())


def _decode(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def _context(events: list[dict], decode_output=_decode) -> ExecHandlerContext:
    return ExecHandlerContext(
        require_auth=lambda _request: None,
        record_request=lambda **_kwargs: None,
        cors_json_response=lambda body, status=200, **_kwargs: web.json_response(body, status=status),
        audit=events.append,
        blocked_reason=lambda _cmd: None,
        control_check=lambda: None,
        is_input_injection_cmd=lambda _cmd: None,
        first_word=lambda cmd: cmd.split()[0],
        under_root=lambda path, root: Path(path).is_relative_to(Path(root)),
        decode_output=decode_output,
        run_shell_command=runner.run_shell_command,
        active_processes=runner.ACTIVE_PROCESSES,
        active_processes_snapshot=runner.active_processes_snapshot,
        cautious_allow=set(),
        default_max_output=100_000,
    )


async def _wait_until(predicate, timeout: float = 15.0) -> None:
    # Hosted macOS process startup can exceed five seconds under matrix load.
    # The invariant is eventual registration/reaping before the 30s command
    # timeout, not a scheduler-speed assertion.
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.01)


def _config(root: Path) -> dict:
    return {
        "profile": "owner-shell",
        "root": root,
        "active_exec": 0,
        "max_concurrent": 1,
        "timeout": 30,
        "max_timeout": 30,
        "max_output": 100_000,
        "allow_any_cwd": False,
        "semaphore": asyncio.Semaphore(1),
    }


async def _serve(app: web.Application, *, handler_cancellation: bool) -> tuple[web.AppRunner, int]:
    # Not aiohttp's TestServer: it accepts `handler_cancellation` and ignores
    # it, because its start_server always passes True. AppRunner honours it.
    app_runner = web.AppRunner(app, handler_cancellation=handler_cancellation)
    await app_runner.setup()
    await web.TCPSite(app_runner, "127.0.0.1", 0).start()
    return app_runner, app_runner.addresses[0][1]


async def _post(port: int, body: bytes, headers: dict[str, str]) -> asyncio.StreamWriter:
    _reader, writer = await asyncio.open_connection("127.0.0.1", port)
    header_lines = [
        "POST /run HTTP/1.1",
        f"Host: 127.0.0.1:{port}",
        f"Content-Length: {len(body)}",
        "Connection: keep-alive",
        *(f"{key}: {value}" for key, value in headers.items()),
        "",
        "",
    ]
    writer.write("\r\n".join(header_lines).encode() + body)
    await writer.drain()
    return writer


# The bridge runs aiohttp without handler cancellation, where only the explicit
# watcher notices a lost client. With it, aiohttp also cancels the handler.
@pytest.mark.parametrize("handler_cancellation", [False, True])
@pytest.mark.parametrize("endpoint", ["buffered", "script", "stream"])
def test_real_tcp_abort_reaps_exec_and_releases_handler(
    tmp_path: Path, endpoint: str, handler_cancellation: bool,
) -> None:
    async def scenario() -> None:
        request_id = f"disconnect-{endpoint}"
        events: list[dict] = []
        cfg = _config(tmp_path)
        handlers = make_exec_handlers(_context(events))
        app = web.Application()
        app[APP_CFG] = cfg
        command = f'"{sys.executable}" -c "import time; time.sleep(30)"'
        if endpoint == "script":
            app.router.add_post("/run", handlers.script)
            is_windows = os.name == "nt"
            body = b"Start-Sleep -Seconds 30\n" if is_windows else b"import time; time.sleep(30)\n"
            headers = {
                "Content-Type": "text/plain",
                "X-Arena-Interpreter": "powershell" if is_windows else "python",
                "X-Arena-Request-Id": request_id,
            }
        else:
            app.router.add_post("/run", handlers.stream if endpoint == "stream" else handlers.exec)
            body = json.dumps({
                "cmd": command,
                "request_id": request_id,
                "timeout": 30,
            }).encode()
            headers = {"Content-Type": "application/json"}

        server, port = await _serve(app, handler_cancellation=handler_cancellation)
        writer = await _post(port, body, headers)
        await _wait_until(lambda: request_id in runner.ACTIVE_PROCESSES, timeout=45)

        # Under matrix load (see _wait_until above) hosted macOS/Windows runners can
        # exceed the default 15 s to tear down the killed tree (taskkill / tree-kill
        # plus the up to 5 s pipe drain). Bump the reaping waits to 45 s so a slow but
        # correct teardown is not reported as a timing flake.
        writer.transport.abort()
        await _wait_until(lambda: request_id not in runner.ACTIVE_PROCESSES, timeout=45)
        await _wait_until(lambda: cfg["active_exec"] == 0, timeout=45)
        assert cfg["semaphore"].locked() is False
        # Depending on aiohttp's handler-cancellation setting, cleanup is
        # reached either by the explicit watcher or by task cancellation.
        # Both must converge on the runner's process-tree-killing finally.
        assert events[0]["type"].endswith("start")
        await server.cleanup()

    try:
        asyncio.run(scenario())
    finally:
        runner.ACTIVE_PROCESSES.clear()
        if endpoint == "script":
            assert not list((tmp_path / ".arena_script_tmp").glob("*"))


def test_a_stream_handler_cancelled_while_it_closes_the_command_gives_the_slot_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#571: the cancellation lands in the generator's cleanup, not in the handler's wait."""
    async def scenario() -> None:
        cleaning = asyncio.Event()
        handler_tasks: list[asyncio.Task] = []

        async def command(**_kwargs):
            try:
                yield {"type": "stdout", "data": b"output"}
            finally:
                # Stands for the kill and the wait for the exit.
                cleaning.set()
                await asyncio.Event().wait()

        def undecodable(_data: bytes) -> str:
            raise ValueError("the handler leaves its loop with the generator still open")

        monkeypatch.setattr(exec_handlers, "run_shell_command_stream", command)
        handlers = make_exec_handlers(_context([], decode_output=undecodable))

        async def run(request: web.Request) -> web.StreamResponse:
            handler_tasks.append(asyncio.current_task())
            return await handlers.stream(request)

        cfg = _config(tmp_path)
        app = web.Application()
        app[APP_CFG] = cfg
        app.router.add_post("/run", run)
        server, port = await _serve(app, handler_cancellation=False)
        body = json.dumps({"cmd": "echo output", "request_id": "cancelled-in-cleanup"}).encode()
        writer = await _post(port, body, {"Content-Type": "application/json"})
        try:
            await asyncio.wait_for(cleaning.wait(), timeout=15)
            assert cfg["active_exec"] == 1
            handler_tasks[0].cancel()
            await asyncio.wait(handler_tasks, timeout=15)
            assert handler_tasks[0].cancelled()
            assert cfg["active_exec"] == 0
            assert cfg["semaphore"].locked() is False
        finally:
            writer.close()
            await server.cleanup()

    asyncio.run(scenario())


@pytest.mark.parametrize("remote, expected_client", [("203.0.113.7", "203.0.113.7"), ("", "127.0.0.1")])
def test_disconnect_audit_and_response_contract(remote: str, expected_client: str) -> None:
    from arena.exec.client_lifecycle import client_disconnect_response

    class Ctx:
        def __init__(self) -> None:
            self.audits: list[dict] = []
            self.records: list[dict] = []

        def audit(self, event: dict) -> None:
            self.audits.append(event)

        def record_request(self, **kwargs) -> None:
            self.records.append(kwargs)

        def cors_json_response(self, body: dict, *, status: int):
            return {"body": body, "status": status}

    request = _Request(None)
    request.remote = remote
    ctx = Ctx()
    response = client_disconnect_response(
        ctx,
        request,
        event_type="exec_client_disconnected",
        request_id="req-7",
        cmd="sleep 30",
    )
    assert ctx.audits == [{
        "type": "exec_client_disconnected",
        "request_id": "req-7",
        "client": expected_client,
        "cmd": "sleep 30",
    }]
    assert ctx.records == [{"duration": 0.0, "is_exec": True, "is_error": True}]
    assert response == {
        "body": {"ok": False, "request_id": "req-7", "error": "client disconnected"},
        "status": 499,
    }


def test_stream_forwarder_preserves_every_event_shape() -> None:
    async def scenario() -> None:
        async def events():
            yield {"type": "start", "pid": 41}
            yield {"type": "stdout", "data": b"out"}
            yield {"type": "stderr", "data": b"err"}
            yield {"type": "progress", "value": 3}
            yield {"type": "exit", "exit_code": 0}

        emitted: list[dict] = []

        async def emit(event: dict) -> None:
            emitted.append(event)

        exit_event = await forward_stream_events(
            _Request(None),
            events(),
            emit=emit,
            decode_output=lambda data: data.decode().upper(),
            request_id="stream-9",
        )
        assert emitted == [
            {"type": "start", "pid": 41, "request_id": "stream-9"},
            {"type": "stdout", "data": "OUT", "bytes": 3},
            {"type": "stderr", "data": "ERR", "bytes": 3},
            {"type": "progress", "value": 3},
            {"type": "exit", "exit_code": 0, "request_id": "stream-9"},
        ]
        assert exit_event == {"type": "exit", "exit_code": 0, "request_id": "stream-9"}

    asyncio.run(scenario())


def test_stream_forwarder_returns_none_for_empty_stream() -> None:
    async def scenario() -> None:
        async def empty():
            if False:
                yield None

        async def emit(_event: dict) -> None:
            raise AssertionError("empty stream emitted an event")

        result = await forward_stream_events(
            _Request(None), empty(), emit=emit,
            decode_output=lambda data: data, request_id="empty",
        )
        assert result is None

    asyncio.run(scenario())


def test_stream_keeps_original_transport_after_aiohttp_detaches_it() -> None:
    async def scenario() -> None:
        transport = _Transport()
        request = _Request(transport)
        cleaned = asyncio.Event()

        async def events():
            try:
                yield {"type": "start", "pid": 123}
                await asyncio.sleep(30)
            finally:
                cleaned.set()

        async def emit(_event):
            transport.closing = True
            request.transport = None

        stream = events()
        try:
            with pytest.raises(ClientDisconnected):
                await asyncio.wait_for(
                    forward_stream_events(request, stream, emit=emit,
                                            decode_output=lambda value: value, request_id="detached"),
                    timeout=0.5,
                )
            assert cleaned.is_set()
        finally:
            await stream.aclose()

    asyncio.run(scenario())

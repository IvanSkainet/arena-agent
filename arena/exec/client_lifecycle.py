"""Bind long-running exec work to the lifetime of its HTTP client."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any


class ClientDisconnected(ConnectionError):
    """The HTTP transport closed before the awaited exec work finished."""


async def await_while_client_connected(
    request: Any,
    awaitable: Awaitable[Any],
    *,
    poll_interval: float = 0.05,
) -> Any:
    """Await work, cancelling it promptly when the request transport closes.

    aiohttp intentionally does not cancel a buffered request handler merely
    because its peer disappeared.  Without an explicit transport watcher a
    silent command can therefore outlive a dead proxy/client until its server
    timeout.  Cancellation reaches ``run_shell_command``'s ``finally`` block,
    which kills and reaps the complete process tree.

    Requests without a transport occur in direct unit calls.  They retain the
    ordinary await semantics rather than being mistaken for a disconnect.
    """
    worker = asyncio.ensure_future(awaitable)
    transport = getattr(request, "transport", None)
    if transport is None:
        return await worker

    async def _wait_for_disconnect() -> None:
        while not transport.is_closing():
            await asyncio.sleep(poll_interval)

    watcher = asyncio.create_task(_wait_for_disconnect())
    try:
        done, _pending = await asyncio.wait(
            (worker, watcher),
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Completion wins a same-loop race with a closing keep-alive socket.
        if worker in done:
            return await worker
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        raise ClientDisconnected("HTTP client disconnected during exec")
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        # Also cover cancellation of the handler itself during the wait.  A
        # detached worker would otherwise retain the subprocess indefinitely.
        if not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


def record_client_disconnect(
    ctx: Any,
    request: Any,
    *,
    event_type: str,
    request_id: str,
    **details: Any,
) -> None:
    """Emit one consistent audit/accounting record for an aborted exec."""
    event = {
        "type": event_type,
        "request_id": request_id,
        "client": request.remote or "127.0.0.1",
    }
    event.update(details)
    ctx.audit(event)
    ctx.record_request(duration=0.0, is_exec=True, is_error=True)


def client_disconnect_response(
    ctx: Any,
    request: Any,
    *,
    event_type: str,
    request_id: str,
    **details: Any,
) -> Any:
    """Audit an aborted buffered exec and build its best-effort 499 reply."""
    record_client_disconnect(
        ctx, request, event_type=event_type, request_id=request_id, **details,
    )
    return ctx.cors_json_response(
        {"ok": False, "request_id": request_id, "error": "client disconnected"},
        status=499,
    )


async def forward_stream_events(
    request: Any,
    stream: Any,
    *,
    emit: Any,
    decode_output: Any,
    request_id: str,
) -> dict[str, Any] | None:
    """Forward runner events while binding every silent wait to the client."""
    exit_event = None
    while True:
        try:
            event = await await_while_client_connected(request, anext(stream))
        except StopAsyncIteration:
            return exit_event
        event_type = event["type"]
        if event_type in ("stdout", "stderr"):
            data = event["data"]
            await emit({"type": event_type, "data": decode_output(data), "bytes": len(data)})
        elif event_type == "start":
            await emit({"type": "start", "pid": event.get("pid"), "request_id": request_id})
        elif event_type == "exit":
            exit_event = dict(event)
            exit_event["request_id"] = request_id
            await emit(exit_event)
        else:
            await emit(event)

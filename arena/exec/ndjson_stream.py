"""Opening and closing out the /v1/exec/stream NDJSON response.

Separate from `arena/exec/handlers.py` so the streaming handler reads as
its lifecycle rather than its plumbing -- CodeScene flagged it as a Bumpy
Road once the concurrency guard added another level of nesting.
"""
from __future__ import annotations

from aiohttp import web

from arena.web_utils import CORS_HEADERS

__all__ = ["close_command_stream", "prepared_ndjson_response", "record_stream_outcome"]


async def prepared_ndjson_response(
        request: web.Request, request_id: str) -> web.StreamResponse:
    """Open the NDJSON stream: chunked transfer, one JSON object per line.

    `X-Accel-Buffering: no` is a hint for reverse proxies (nginx) not to
    coalesce chunks -- it matters when the bridge sits behind a Tailscale
    funnel or similar. The response itself is unbuffered from aiohttp.
    """
    headers = dict(CORS_HEADERS)
    headers["Content-Type"] = "application/x-ndjson"
    headers["Cache-Control"] = "no-cache"
    headers["X-Accel-Buffering"] = "no"
    headers["X-Arena-Request-Id"] = request_id
    response = web.StreamResponse(status=200, headers=headers)
    response.enable_chunked_encoding()
    await response.prepare(request)
    return response


async def close_command_stream(stream, slot) -> None:
    """Close the runner's generator and give the exec slot back.

    Closing kills a command that is still running and waits for its exit.
    The handler can be cancelled during that wait (#571), so the slot is
    released whatever happens to the close. `stream` is None when the
    handler failed before it started a command.
    """
    try:
        if stream is not None:
            await stream.aclose()
    finally:
        slot.release()


def record_stream_outcome(ctx, exit_event: dict | None, *,
                           request_id: str, cmd: str) -> None:
    """Audit and record a finished stream, however it ended.

    Every field is conditional on `exit_event` being there at all -- a
    disconnect leaves it None -- which is a lot of ternaries for one
    handler to carry inline (CodeScene, Bumpy Road).
    """
    event = exit_event or {}
    duration = float(event.get("duration_sec", 0.0))
    timed_out = bool(event.get("timed_out"))
    exit_code = event.get("exit_code")
    ctx.audit({
        "type": "exec_stream_timeout" if timed_out else "exec_stream_done",
        "request_id": request_id, "cmd": cmd,
        "exit_code": exit_code, "duration": duration,
        "truncated": bool(event.get("truncated")),
        "stdout_bytes": event.get("stdout_bytes", 0),
        "stderr_bytes": event.get("stderr_bytes", 0)})
    ctx.record_request(duration=duration, is_exec=True,
                       is_error=timed_out or (exit_code != 0))

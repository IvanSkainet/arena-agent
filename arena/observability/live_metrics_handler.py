"""HTTP + WebSocket handlers for /v1/live-metrics (v3.95.0).

`handle_v1_live_metrics` returns a single snapshot (JSON GET) --
useful for scripting agents and one-shot inspection.

`handle_v1_live_metrics_stream` upgrades to WebSocket and pushes a
snapshot approximately once per second, until the client closes.
The Dashboard's Live tab uses the WebSocket path for smooth
sparkline updates.
"""
from __future__ import annotations

import asyncio
import json
import logging

from aiohttp import WSCloseCode, WSMsgType, web

from arena.handler_helpers import authed, err_json
from arena.observability.live_metrics import live_metrics_snapshot

_LOG = logging.getLogger(__name__)

# Server tick rate for the WebSocket. 1Hz keeps the ~2KB payload
# well under any reasonable network budget while still feeling
# "live" in the browser (Canvas repaint is 60fps but we drive it
# at data-arrival cadence).
_STREAM_INTERVAL_SEC = 1.0

# Safety cap on the number of concurrent stream clients per
# process. A rogue Dashboard tab left open shouldn't be able to
# monopolise the event loop; 32 is far more than any realistic
# deployment needs.
_MAX_STREAM_CLIENTS = 32

# Module-level counter of active stream clients. Held here rather
# than on ctx because the context objects are frozen dataclasses
# (setattr would raise FrozenInstanceError). Guarded by asyncio's
# single-thread cooperative scheduling — no lock needed since the
# increment/decrement happen only on the event loop.
_ACTIVE_STREAM_CLIENTS = 0


def _stream_clients_count() -> int:
    """Test-visible accessor for the live stream client counter."""
    return _ACTIVE_STREAM_CLIENTS


def make_live_metrics_handlers(ctx):
    """Return the two handler coroutines for live metrics.

    ``ctx`` needs the standard context fields: ``require_auth``,
    ``record_request``, ``cors_json_response``. WebSocket clients
    are auth-checked exactly the same way as REST callers -- the
    initial upgrade request must carry the Bearer token.
    """

    @authed(ctx)
    async def handle_v1_live_metrics(request: web.Request) -> web.Response:
        """GET /v1/live-metrics -- one-shot snapshot."""
        snap = live_metrics_snapshot()
        return ctx.cors_json_response(snap)

    # WebSocket: @authed is intentionally NOT used -- we need to
    # own the response object so we can return a WebSocketResponse
    # on success, but still enforce auth manually first.
    async def handle_v1_live_metrics_stream(request: web.Request) -> web.WebSocketResponse:
        """GET /v1/live-metrics/stream -- 1Hz WebSocket push."""
        auth_err = ctx.require_auth(request)
        if auth_err is not None:
            # Return the auth error as a plain JSON response --
            # aiohttp lets a WebSocket route return a Response
            # instead of upgrading if it wants.
            return auth_err  # type: ignore[return-value]

        global _ACTIVE_STREAM_CLIENTS
        if _ACTIVE_STREAM_CLIENTS >= _MAX_STREAM_CLIENTS:
            return err_json(
                ctx,
                f"too many live-metrics stream clients ({_ACTIVE_STREAM_CLIENTS}); "
                f"cap is {_MAX_STREAM_CLIENTS}",
                status=429,
            )  # type: ignore[return-value]

        ctx.record_request()

        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=1 << 20)
        # WebSocket clients don't get CORS headers via prepare(),
        # but browsers don't apply CORS to same-origin WebSocket
        # anyway. If a cross-origin client needs it, we could plumb
        # ctx.cors_json_response's origin handling in later.
        await ws.prepare(request)

        # Bump/decrement the module-level client counter around
        # the whole loop. Context is a frozen dataclass so we
        # can't hang state off it directly.
        _ACTIVE_STREAM_CLIENTS += 1
        try:
            await _stream_loop(ws)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOG.exception("live-metrics stream crashed")
        finally:
            _ACTIVE_STREAM_CLIENTS = max(0, _ACTIVE_STREAM_CLIENTS - 1)
            if not ws.closed:
                try:
                    await ws.close(code=WSCloseCode.OK, message=b"bye")
                except Exception:
                    pass
        return ws

    return {
        "live_metrics": handle_v1_live_metrics,
        "live_metrics_stream": handle_v1_live_metrics_stream,
    }


async def _stream_loop(ws: web.WebSocketResponse) -> None:
    """Push snapshots at ~1Hz until the client closes or sends a
    ``close``/``error`` frame. Handles ``ping`` frames automatically
    via aiohttp's heartbeat feature."""
    # Drain incoming frames on a side task so a chatty client can't
    # block our writes. We only care about close/error signals -- any
    # text/binary frame from the client is ignored (no client->server
    # protocol at this time; the client is pure viewer).
    stop = asyncio.Event()

    async def _drain() -> None:
        async for msg in ws:
            if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                stop.set()
                return

    drain_task = asyncio.create_task(_drain())
    try:
        while not stop.is_set() and not ws.closed:
            snap = live_metrics_snapshot()
            payload = json.dumps(snap, separators=(",", ":"))
            try:
                await ws.send_str(payload)
            except (ConnectionResetError, RuntimeError):
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=_STREAM_INTERVAL_SEC)
            except asyncio.TimeoutError:
                pass
    finally:
        stop.set()
        drain_task.cancel()
        try:
            await drain_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

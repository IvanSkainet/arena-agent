"""Handlers for WebSocket realtime event streams."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp import web

from arena.events.runtime import EVENT_SUBSCRIBERS
from arena.handler_context import EventHandlerContext


def _needs_upgrade(ctx: EventHandlerContext, why: str) -> web.Response:
    """The one answer for every request that is not a WebSocket handshake."""
    return ctx.cors_json_response(
        {"ok": False,
         "error": f"GET /v1/events is a WebSocket endpoint; {why}",
         "upgrade": "websocket"},
        status=426,
        extra_headers={"Upgrade": "websocket", "Connection": "Upgrade"},
    )


def _is_websocket_upgrade(request: web.Request) -> bool:
    """Whether this request is asking for the WebSocket handshake.

    Both headers, because either one alone is a malformed handshake that
    aiohttp would refuse anyway, and `Connection` is a comma-separated
    list in the wild (`keep-alive, Upgrade`).
    """
    connection = request.headers.get("Connection", "")
    tokens = {part.strip().lower() for part in connection.split(",")}
    return (request.headers.get("Upgrade", "").lower() == "websocket"
            and "upgrade" in tokens)


async def _upgraded_socket(
        ctx: EventHandlerContext, request: web.Request,
) -> tuple[web.WebSocketResponse | None, web.StreamResponse | None]:
    """The open socket, or the HTTP answer to send instead.

    Three ways a request never becomes a stream, all of them answered
    before a frame is sent (#258):

    * no credential -- a 401 in HTTP, like every other operation. The
      handshake used to complete and then say `unauthorized` in a
      WebSocket frame: an anonymous caller got a live socket, the
      failed-auth throttle never saw the attempt, and a client reading
      status codes saw a success;
    * no upgrade headers -- a 426, since aiohttp's own answer is a
      plain-text 400 ("No WebSocket UPGRADE hdr"), neither the JSON shape
      every other error uses nor a code the document mentions;
    * upgrade headers but an incomplete handshake (no `Sec-WebSocket-Key`,
      an unsupported version) -- the same 426, with aiohttp's reason
      attached.
    """
    refusal = ctx.require_auth(request)
    if refusal:
        return None, refusal
    if not _is_websocket_upgrade(request):
        return None, _needs_upgrade(ctx, "send Upgrade: websocket to connect")
    ws = web.WebSocketResponse()
    try:
        await ws.prepare(request)
    except web.HTTPException as exc:
        return None, _needs_upgrade(ctx, str(exc.text or exc.reason))
    return ws, None


async def _forward_events(ctx: EventHandlerContext, ws: web.WebSocketResponse,
                          q: "asyncio.Queue[Any]") -> None:
    """Pump the subscriber queue into the socket, pinging when it is idle.

    Any send failure ends the forwarder -- a socket that cannot take a
    frame is a socket that is gone -- but it says which one it was first.
    A stream that stops with no line in the log leaves an operator with a
    disconnected client and no cause (corgea).
    """
    while not ws.closed:
        try:
            payload = await asyncio.wait_for(q.get(), timeout=30)
            if not ws.closed:
                await ws.send_json(payload)
        except asyncio.TimeoutError:
            if ws.closed:
                continue
            try:
                await ws.send_json({"type": "ping", "ts": ctx.utc_now()})
            except Exception as exc:
                ctx.log_info("[Events] Keepalive ping failed, closing stream: %r", exc)
                break
        except Exception as exc:
            ctx.log_info("[Events] Event forwarding stopped: %r", exc)
            break


def _client_command(raw: Any) -> str | None:
    """The `command` field of a client frame, or None if there is not one.

    Anything a client sends can be malformed, so a frame that is not JSON,
    not an object, or has no command is simply not a command. Returning
    None says that without a swallowed exception in the read loop, which
    is the shape bandit counts (B110/B112).
    """
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, RecursionError):
        # RecursionError belongs here: a deeply nested frame is malformed
        # input like any other, and letting it escape would end the stream
        # a client could keep alive by sending garbage (cubic).
        return None
    if not isinstance(data, dict):
        return None
    command = data.get("command")
    return command if isinstance(command, str) else None


async def _read_client_messages(ctx: EventHandlerContext, ws: web.WebSocketResponse) -> None:
    """Read the socket until the client stops talking.

    Only `ping` means anything today; the loop exists so that a close or
    an error ends the stream instead of leaving the forwarder running.
    """
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            if _client_command(msg.data) != "ping":
                continue
            try:
                await ws.send_json({"type": "pong", "ts": ctx.utc_now()})
            except Exception as exc:
                # A failed reply ends the read loop rather than escaping it:
                # an exception here would skip the forwarder's cancellation
                # in `_stream_until_closed` and leave that task waiting on a
                # queue nobody publishes to any more (cubic).
                ctx.log_info("[Events] Pong failed, closing stream: %r", exc)
                break
        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
            break


async def _stream_until_closed(ctx: EventHandlerContext, ws: web.WebSocketResponse) -> None:
    """Subscribe, run both directions of the stream, unsubscribe."""
    q: asyncio.Queue[Any] = asyncio.Queue(maxsize=500)
    EVENT_SUBSCRIBERS.append(q)
    ctx.log_info("[Events] Subscriber connected (total=%d)", len(EVENT_SUBSCRIBERS))
    forward_task = asyncio.create_task(_forward_events(ctx, ws, q))
    try:
        await _read_client_messages(ctx, ws)
    finally:
        forward_task.cancel()
        try:
            await forward_task
        except asyncio.CancelledError:
            pass
        if q in EVENT_SUBSCRIBERS:
            EVENT_SUBSCRIBERS.remove(q)
        ctx.log_info("[Events] Subscriber disconnected (total=%d)", len(EVENT_SUBSCRIBERS))


@dataclass(frozen=True)
class EventHandlers:
    events: Callable[..., Any]


def make_event_handlers(ctx: EventHandlerContext) -> EventHandlers:
    async def handle_v1_events(request: web.Request) -> web.StreamResponse:
        """WebSocket /v1/events — Real-time event stream.

        Clients connect via WebSocket and receive events as JSON messages.
        Events include: cdp_connect, cdp_disconnect, task_start, task_done,
        error, skill_run, exec, memory_update, browser_browse, alert,
        and file_watch_change.

        What answers before the stream opens -- 401 without a credential,
        426 without a handshake -- is in `_upgraded_socket` (#258).
        """
        ws, refusal = await _upgraded_socket(ctx, request)
        if ws is None:
            # `refusal` is always set when the socket is not -- spelled as
            # a check on the socket rather than an assert, since asserts
            # vanish under PYTHONOPTIMIZE and this one guards a return
            # value (aikido).
            return refusal or _needs_upgrade(ctx, "the handshake did not complete")
        await ws.send_json({"type": "connected", "ts": ctx.utc_now(),
                            "data": {"version": ctx.version,
                                     "message": "Arena Bridge event stream"}})
        await _stream_until_closed(ctx, ws)
        return ws

    return EventHandlers(events=handle_v1_events)

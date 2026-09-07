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

        Two answers before the upgrade, both added in #258 because the
        fuzzing gate reads the document and this operation did not keep to
        it:

        * No credential is a 401 in HTTP, like every other operation. It
          used to complete the handshake and then say `unauthorized` in a
          WebSocket frame -- an anonymous caller got a live socket, the
          failed-auth throttle never saw the attempt, and a client reading
          status codes saw a success.
        * A plain GET is a 426. aiohttp answers its own 400 with a
          plain-text body ("No WebSocket UPGRADE hdr"), which is neither
          the JSON shape every other error uses nor a code the document
          mentions.
        """
        r = ctx.require_auth(request)
        if r:
            return r

        if not _is_websocket_upgrade(request):
            return _needs_upgrade(ctx, "send Upgrade: websocket to connect")

        ws = web.WebSocketResponse()
        try:
            await ws.prepare(request)
        except web.HTTPException as exc:
            # The headers said "upgrade" but the handshake was incomplete --
            # no `Sec-WebSocket-Key`, an unsupported version. aiohttp raises
            # its own plain-text 400 for those, which is the same
            # undocumented answer in a different disguise, so it becomes the
            # same 426 with the reason attached.
            return _needs_upgrade(ctx, str(exc.text or exc.reason))

        # Send welcome message.
        await ws.send_json({"type": "connected", "ts": ctx.utc_now(),
                            "data": {"version": ctx.version, "message": "Arena Bridge event stream"}})

        # Subscribe.
        q: asyncio.Queue[Any] = asyncio.Queue(maxsize=500)
        EVENT_SUBSCRIBERS.append(q)
        ctx.log_info("[Events] Subscriber connected (total=%d)", len(EVENT_SUBSCRIBERS))

        try:
            # Two-task pattern: read from ws AND forward events from queue.
            async def _forward_events():
                while not ws.closed:
                    try:
                        payload = await asyncio.wait_for(q.get(), timeout=30)
                        if not ws.closed:
                            await ws.send_json(payload)
                    except asyncio.TimeoutError:
                        # Send keepalive ping.
                        if not ws.closed:
                            try:
                                await ws.send_json({"type": "ping", "ts": ctx.utc_now()})
                            except Exception:
                                break
                    except Exception:
                        break

            forward_task = asyncio.create_task(_forward_events())

            # Also read incoming messages (for future commands).
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        # Support subscribe/unsubscribe by event type.
                        if data.get("command") == "ping":
                            await ws.send_json({"type": "pong", "ts": ctx.utc_now()})
                    except Exception:
                        pass
                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    break

            forward_task.cancel()
            try:
                await forward_task
            except asyncio.CancelledError:
                pass
        finally:
            if q in EVENT_SUBSCRIBERS:
                EVENT_SUBSCRIBERS.remove(q)
            ctx.log_info("[Events] Subscriber disconnected (total=%d)", len(EVENT_SUBSCRIBERS))

        return ws

    return EventHandlers(events=handle_v1_events)

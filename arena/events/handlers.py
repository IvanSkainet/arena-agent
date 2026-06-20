"""Handlers for WebSocket realtime event streams."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp import web

from arena.events.runtime import EVENT_SUBSCRIBERS
from arena.handler_context import EventHandlerContext


@dataclass(frozen=True)
class EventHandlers:
    events: object


def make_event_handlers(ctx: EventHandlerContext) -> EventHandlers:
    async def handle_v1_events(request: web.Request) -> web.WebSocketResponse:
        """WebSocket /v1/events — Real-time event stream.

        Clients connect via WebSocket and receive events as JSON messages.
        Events include: cdp_connect, cdp_disconnect, task_start, task_done,
        error, skill_run, exec, memory_update, browser_browse, alert,
        and file_watch_change.
        """
        r = ctx.require_auth(request)
        if r:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"ok": False, "error": "unauthorized"})
            await ws.close()
            return ws

        ws = web.WebSocketResponse()
        await ws.prepare(request)

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

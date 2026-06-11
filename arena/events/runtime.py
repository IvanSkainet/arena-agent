"""Realtime event broadcast runtime."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

EVENT_SUBSCRIBERS: list[asyncio.Queue] = []


async def emit_event(
    event_type: str,
    data: dict | None = None,
    *,
    utc_now_fn: Callable[[], str],
) -> None:
    """Broadcast an event to all connected WebSocket subscribers."""
    payload = {"type": event_type, "ts": utc_now_fn(), "data": data or {}}
    dead: list[asyncio.Queue[Any]] = []
    for q in list(EVENT_SUBSCRIBERS):  # Iterate over copy to avoid race.
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    # Remove full/dead queues.
    for q in dead:
        try:
            EVENT_SUBSCRIBERS.remove(q)
        except ValueError:
            pass

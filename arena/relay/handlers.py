"""HTTP surface for the operator <-> agent mailbox.

Five endpoints, all authenticated like everything else on the bridge:

    POST /v1/relay/send      operator queues a message
    GET  /v1/relay/poll      agent claims the next one (long-poll)
    POST /v1/relay/reply     agent answers a claimed message
    GET  /v1/relay/replies   operator collects answers (long-poll)
    GET  /v1/relay/status    queue depth + is anyone actually listening

The long-poll is what makes this feel like a conversation instead of a
dead drop, and it is also the part that needs care. Two rules:

**The wait must never exceed the client's patience.** `wait` is clamped
to `MAX_WAIT_S`; a request that parks a worker thread for minutes is a
denial of service against a bridge that only has `max_concurrent`
workers. The default is deliberately under the 30s that most proxies and
tunnels use as an idle timeout.

**Polling must be recorded even when it finds nothing.** That is how
`send` can tell the operator "an agent is listening" rather than printing
"sent" into the void. Getting this backwards -- reporting delivery to
nobody -- is the same failure as the token-rotation note in bug #66.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from arena.handler_helpers import authed
from arena.relay import store

# A long-poll longer than this risks being cut by a tunnel or proxy
# mid-flight, which looks to the caller like a lost message.
MAX_WAIT_S = 25.0

# How recently an agent must have polled before `send` will claim someone
# is listening. Generous enough to cover one full long-poll cycle plus
# the round trip.
POLL_FRESH_S = 60.0


@dataclass(frozen=True)
class RelayHandlers:
    relay_send: Callable[..., Any]
    relay_poll: Callable[..., Any]
    relay_reply: Callable[..., Any]
    relay_replies: Callable[..., Any]
    relay_status: Callable[..., Any]


def _clamp_wait(raw: Any, *, default: float = 0.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return max(0.0, min(value, MAX_WAIT_S))


def make_relay_handlers(ctx) -> RelayHandlers:
    """Build the relay endpoints.

    `ctx` supplies `relay_root()` (a Path), plus the usual bridge
    plumbing: require_auth, record_request, cors_json_response, executor,
    audit.
    """
    # Process-global, like the metrics sample: several handlers need to
    # agree on when an agent last showed interest.
    last_poll: dict[str, float] = {"at": 0.0}

    @authed(ctx)
    async def handle_v1_relay_send(request: web.Request) -> web.Response:
        """POST /v1/relay/send — queue a message for the agent."""
        try:
            data = await request.json()
        except Exception as exc:  # noqa: BLE001 -- any parse error is a 400
            return ctx.cors_json_response(
                {"ok": False, "error": f"invalid json: {exc}"}, status=400)

        body = data.get("body", "")
        sender = str(data.get("sender") or "operator")[:64]
        loop = asyncio.get_running_loop()
        root = ctx.relay_root()
        try:
            msg = await loop.run_in_executor(
                ctx.executor, lambda: store.send_message(
                    root, body, sender=sender, meta=data.get("meta") or {}))
        except ValueError as exc:
            return ctx.cors_json_response(
                {"ok": False, "error": str(exc)}, status=400)

        age = time.monotonic() - last_poll["at"] if last_poll["at"] else None
        polling = age is not None and age < POLL_FRESH_S
        depth = await loop.run_in_executor(
            ctx.executor, lambda: store.inbox_depth(root))
        ctx.audit({"type": "relay.send", "id": msg.id, "sender": sender,
                   "bytes": len(body.encode("utf-8")), "agent_polling": polling})
        return ctx.cors_json_response({
            "ok": True,
            "id": msg.id,
            "inbox_depth": depth,
            # The honest bit: say whether anyone is actually there.
            "agent_polling": polling,
            "last_poll_age_s": age,
        })

    @authed(ctx)
    async def handle_v1_relay_poll(request: web.Request) -> web.Response:
        """GET /v1/relay/poll?wait=25 — agent claims the next message."""
        # Record interest FIRST. An agent that polls an empty inbox is
        # still an agent that is listening, and the operator needs to
        # know that before deciding whether to wait for a reply.
        last_poll["at"] = time.monotonic()
        wait = _clamp_wait(request.query.get("wait", "25"), default=25.0)
        root = ctx.relay_root()
        loop = asyncio.get_running_loop()
        msg = await loop.run_in_executor(
            ctx.executor, lambda: store.wait_for_message(root, timeout=wait))
        if msg is None:
            return ctx.cors_json_response({"ok": True, "message": None})
        ctx.audit({"type": "relay.claim", "id": msg.id, "sender": msg.sender})
        return ctx.cors_json_response({"ok": True, "message": msg.to_dict()})

    @authed(ctx)
    async def handle_v1_relay_reply(request: web.Request) -> web.Response:
        """POST /v1/relay/reply — agent answers a claimed message."""
        try:
            data = await request.json()
        except Exception as exc:  # noqa: BLE001
            return ctx.cors_json_response(
                {"ok": False, "error": f"invalid json: {exc}"}, status=400)
        loop = asyncio.get_running_loop()
        root = ctx.relay_root()
        try:
            msg = await loop.run_in_executor(
                ctx.executor, lambda: store.post_reply(
                    root, str(data.get("in_reply_to") or ""),
                    data.get("body", ""),
                    sender=str(data.get("sender") or "agent")[:64]))
        except ValueError as exc:
            return ctx.cors_json_response(
                {"ok": False, "error": str(exc)}, status=400)
        ctx.audit({"type": "relay.reply", "id": msg.id,
                   "in_reply_to": data.get("in_reply_to")})
        return ctx.cors_json_response({"ok": True, "id": msg.id})

    @authed(ctx)
    async def handle_v1_relay_replies(request: web.Request) -> web.Response:
        """GET /v1/relay/replies?in_reply_to=&wait=0 — collect answers."""
        target = request.query.get("in_reply_to", "")
        wait = _clamp_wait(request.query.get("wait", "0"))
        root = ctx.relay_root()
        loop = asyncio.get_running_loop()
        if wait > 0 and target:
            msg = await loop.run_in_executor(
                ctx.executor,
                lambda: store.wait_for_reply(root, target, timeout=wait))
            found = [msg] if msg is not None else []
        else:
            found = await loop.run_in_executor(
                ctx.executor,
                lambda: store.read_replies(root, in_reply_to=target))
        return ctx.cors_json_response(
            {"ok": True, "replies": [m.to_dict() for m in found]})

    @authed(ctx)
    async def handle_v1_relay_status(request: web.Request) -> web.Response:
        """GET /v1/relay/status — depth, and whether an agent is polling."""
        root = ctx.relay_root()
        loop = asyncio.get_running_loop()
        depth = await loop.run_in_executor(
            ctx.executor, lambda: store.inbox_depth(root))
        replies = await loop.run_in_executor(
            ctx.executor,
            lambda: len(store.read_replies(root, consume=False)))
        age = time.monotonic() - last_poll["at"] if last_poll["at"] else None
        return ctx.cors_json_response({
            "ok": True,
            "inbox_depth": depth,
            "reply_depth": replies,
            "last_poll_age_s": age,
            "agent_polling": age is not None and age < POLL_FRESH_S,
            "max_wait_s": MAX_WAIT_S,
        })

    return RelayHandlers(
        relay_send=handle_v1_relay_send,
        relay_poll=handle_v1_relay_poll,
        relay_reply=handle_v1_relay_reply,
        relay_replies=handle_v1_relay_replies,
        relay_status=handle_v1_relay_status,
    )

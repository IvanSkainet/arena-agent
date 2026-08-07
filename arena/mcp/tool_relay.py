"""MCP tools for the operator mailbox: relay.check, relay.reply, relay.send.

Why these exist
---------------
The relay already works over HTTP and from a terminal, but both require
somebody to *remember* it. An MCP tool turns the mailbox into something
the agent can see in its own tool list and reach for on its own -- the
difference between a channel that exists and a channel that gets used.

`relay.check` is deliberately **non-blocking by default**. A tool that
parks the session for 25 seconds every time it is called teaches the
agent not to call it. The default is "look now, tell me what is there",
which costs milliseconds and can be done between steps without thinking
about it. `wait` is available for the cases where the agent has genuinely
finished and wants to give the operator a moment to respond.

The honesty rule from the HTTP layer carries over: `relay.send` reports
whether an operator-side reader is plausibly there, and never claims a
message was received when it was only queued.

Cross-process note: these tools read the same directory the HTTP
endpoints use, so a message left in the Dashboard, from `bin/arena-relay`
or by a previous session is visible here. `claim_next` renames the file,
so two concurrent sessions cannot both act on the same instruction.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.relay import store

RELAY_TOOL_NAMES = frozenset({"relay.check", "relay.reply", "relay.send"})

# Same cap as the HTTP layer, and for the same reason: a longer block
# outlives typical proxy idle timeouts and wastes a worker.
MAX_WAIT_S = 25.0


def _relay_root(ctx) -> Path:
    """Where the mailbox lives.

    Resolved through the same ROOT_AGENT the HTTP handlers use so all
    three surfaces (MCP, REST, CLI) share one queue. Falling back to a
    private directory would silently split the conversation in two, which
    is worse than failing.
    """
    getter = getattr(ctx, "relay_root", None)
    if callable(getter):
        resolved = getter()
        # The context declares this as Callable[[], Any], so narrow it here
        # rather than handing an unknown straight to Path().
        if isinstance(resolved, Path):
            return resolved
        return Path(str(resolved))
    # No fallback on purpose. The first version of this function fell back
    # to `bridge_dir`, which on the operator's machine is a DIFFERENT path
    # from the ROOT_AGENT the HTTP handlers use -- so a message sent from
    # the Dashboard was invisible to relay.check and vice versa. Verified
    # by running both surfaces against one bridge: the mailbox silently
    # split in two, which is worse than an error because both halves look
    # like they work.
    raise RuntimeError(
        "relay tools were wired without relay_root; refusing to guess a "
        "directory, because guessing wrong splits the mailbox in two"
    )


def _clamp_wait(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value != value:
        return 0.0
    return max(0.0, min(value, MAX_WAIT_S))


def handle_relay_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Handle relay.* MCP tools. Returns None for names we do not own."""
    if name not in RELAY_TOOL_NAMES:
        return None

    try:
        root = _relay_root(ctx)
    except RuntimeError as exc:
        return {"isError": True,
                "content": [{"type": "text", "text": f"ERROR: {exc}"}]}

    if name == "relay.check":
        wait = _clamp_wait(args.get("wait", 0))
        msg = (store.wait_for_message(root, timeout=wait) if wait > 0
               else store.claim_next(root))
        if msg is None:
            depth = store.inbox_depth(root)
            return text_content(
                "No operator messages waiting."
                + (f" ({depth} arrived after this check.)" if depth else ""))
        age = max(0.0, time.time() - msg.created_at)
        return text_content(
            f"Message from {msg.sender} (id {msg.id}, sent "
            f"{age:.0f}s ago):\n\n{msg.body}\n\n"
            f"Reply with relay.reply(in_reply_to=\"{msg.id}\", body=\"...\").")

    if name == "relay.reply":
        target = str(args.get("in_reply_to") or "").strip()
        body = args.get("body", "")
        if not target:
            return {"isError": True, "content": [{"type": "text", "text":
                    "ERROR: in_reply_to is required (the id from relay.check)"}]}
        try:
            store.post_reply(root, target, body, sender="agent")
        except ValueError as exc:
            return {"isError": True,
                    "content": [{"type": "text", "text": f"ERROR: {exc}"}]}
        return text_content(f"Replied to {target}.")

    # relay.send -- the agent starting a thread, e.g. asking a question
    # mid-task rather than guessing.
    body = args.get("body", "")
    try:
        msg = store.send_message(root, body, sender="agent")
    except ValueError as exc:
        return {"isError": True,
                "content": [{"type": "text", "text": f"ERROR: {exc}"}]}
    return text_content(
        f"Queued as {msg.id}. The operator sees this in the Dashboard "
        f"Relay tab or via `arena-relay recv`. Nothing guarantees they are "
        f"looking right now -- use relay.check(wait=25) if you need an "
        f"answer before continuing.")


RELAY_MCP_TOOLS: list[dict[str, Any]] = [
    {"name": "relay.check",
     "description": (
         "Check the operator mailbox for instructions left from the "
         "Dashboard or a terminal. Returns the oldest unread message and "
         "marks it claimed. Cheap and non-blocking by default -- call it "
         "between steps. Pass wait=25 to block until something arrives."),
     "inputSchema": {"type": "object", "properties": {
         "wait": {"type": "number", "default": 0,
                  "description": "Seconds to block waiting (0-25, default 0)"}},
         "required": [], "additionalProperties": False}},
    {"name": "relay.reply",
     "description": (
         "Answer an operator message returned by relay.check. The reply "
         "appears in the Dashboard Relay tab and in `arena-relay recv`."),
     "inputSchema": {"type": "object", "properties": {
         "in_reply_to": {"type": "string",
                         "description": "Message id from relay.check"},
         "body": {"type": "string", "description": "Reply text"}},
         "required": ["in_reply_to", "body"], "additionalProperties": False}},
    {"name": "relay.send",
     "description": (
         "Send a message to the operator without being asked -- a question "
         "mid-task, or a heads-up. It is queued; the operator may not be "
         "looking. Does not block."),
     "inputSchema": {"type": "object", "properties": {
         "body": {"type": "string", "description": "Message text"}},
         "required": ["body"], "additionalProperties": False}},
]

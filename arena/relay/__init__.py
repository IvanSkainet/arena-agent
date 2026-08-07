"""Operator <-> agent relay: a mailbox, not a remote control.

The idea came from the project's Discord: the tunnel already carries data
both ways, so why can the operator not type at the agent from a terminal
instead of a browser tab?

The honest answer, and the reason this module is shaped the way it is:
**an agent session cannot be started from this side.** Arena is a website
with no public API, and its Terms of Use are explicit -- section 5(vi)
forbids accessing the Service "through programmatic or automated means",
and 5(vii) forbids using "spiders, robots, scrapers, crawlers, avatars"
against it. A headless browser driving arena.ai would be a plain
violation, would break on the next redesign, and would put the operator's
account at risk. So this relay does not attempt it.

What it does instead is the part that is genuinely ours: the bridge runs
on the operator's machine, and the agent is already talking to it. A
message left here is picked up the next time the agent looks. That makes
it a **mailbox with an optional wait**, not a CLI that summons anyone:

    operator                    bridge                    agent
    --------                    ------                    -----
    relay send "..."   ---->    queued
                                            <----  relay poll (long-poll)
                                delivered   ---->  reads it
                                            <----  relay reply "..."
    relay recv         <----    reply

`poll` blocks for up to `wait` seconds, so when the agent is active the
round trip feels immediate. When it is not, the message simply waits --
and `send` says so rather than pretending someone is listening. Claiming
delivery to nobody is the same class of lie as the token-rotation note in
bug #66, and it is avoided for the same reason.

Storage is one JSON file per message under the bridge state directory,
mirroring `arena/tasks/queue.py`, which was deliberately not reused: that
queue *executes* what it is given. Verified against the live bridge --
posting a plain sentence to `/v1/tasks` produced `state: failed,
exit_code: 1`, because the runner tried to run the sentence as a shell
command. A channel for prose has to be a different channel.
"""
from __future__ import annotations

from arena.relay.store import (
    RelayMessage,
    claim_next,
    inbox_depth,
    list_messages,
    post_reply,
    read_replies,
    send_message,
    wait_for_message,
    wait_for_reply,
)

__all__ = [
    "RelayMessage",
    "claim_next",
    "inbox_depth",
    "list_messages",
    "post_reply",
    "read_replies",
    "send_message",
    "wait_for_message",
    "wait_for_reply",
]

"""The relay as MCP tools -- one mailbox across three surfaces.

The relay already worked over HTTP and from a terminal, but both needed
somebody to remember it existed. Listing it in the agent's tool set is
what turns a channel that exists into one that gets used.

The bug this file mostly exists to prevent was found by running it: the
first version derived the mailbox directory from `ctx.bridge_dir`,
because that was the path MCP happened to be handed. The HTTP handlers
use `ROOT_AGENT`, and on the operator's machine those are **different
directories** -- so a message sent from the Dashboard was invisible to
`relay.check`, and the agent's reply was invisible to the operator. Both
halves looked like they were working.

That is worse than a crash, so the fallback is gone: `_relay_root` now
raises rather than guessing. A wiring mistake becomes a loud error
instead of a conversation quietly split in two.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from arena.mcp import tool_relay as R
from arena.relay import store


@pytest.fixture
def ctx(tmp_path):
    root = tmp_path / "relay"
    return types.SimpleNamespace(relay_root=lambda: root), root


def _text(result) -> str:
    return result["content"][0]["text"]


# --------------------------------------------------------------------
# Directory resolution -- the bug that shipped and was caught by running.
# --------------------------------------------------------------------

def test_the_root_comes_from_the_explicit_wiring(ctx):
    context, root = ctx
    assert R._relay_root(context) == root


def test_a_context_without_relay_root_raises_rather_than_guessing():
    """Guessing split the mailbox in two on a real machine.

    `bridge_dir` and `ROOT_AGENT` differ on the operator's install, so
    falling back to whichever attribute happens to exist produced two
    mailboxes that each looked healthy in isolation.
    """
    bare = types.SimpleNamespace(bridge_dir=Path("/somewhere/else"),
                                 root_agent=Path("/another/place"))
    with pytest.raises(RuntimeError, match="splits the mailbox"):
        R._relay_root(bare)


def test_a_missing_root_is_reported_as_a_tool_error_not_a_crash():
    """An MCP handler must answer, not raise into the protocol layer."""
    bare = types.SimpleNamespace()
    result = R.handle_relay_tool("relay.check", {}, ctx=bare)
    assert result["isError"] is True
    assert "relay_root" in _text(result)


# --------------------------------------------------------------------
# The three tools.
# --------------------------------------------------------------------

def test_check_on_an_empty_box_says_so_plainly(ctx):
    context, _root = ctx
    assert "No operator messages" in _text(
        R.handle_relay_tool("relay.check", {}, ctx=context))


def test_check_returns_the_message_and_the_id_needed_to_answer(ctx):
    context, root = ctx
    sent = store.send_message(root, "проверь CI")
    text = _text(R.handle_relay_tool("relay.check", {}, ctx=context))
    assert "проверь CI" in text
    assert sent.id in text
    assert "relay.reply" in text, (
        "the tool output has to tell the agent how to answer, or it will "
        "read the message and drop it"
    )


def test_check_still_claims_when_heartbeat_persistence_fails(ctx, monkeypatch):
    context, root = ctx
    sent = store.send_message(root, "heartbeat must be best effort")

    def fail_heartbeat(*_args, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(store, "record_agent_poll", fail_heartbeat)
    text = _text(R.handle_relay_tool("relay.check", {}, ctx=context))
    assert sent.id in text
    assert "heartbeat must be best effort" in text


def test_check_claims_the_message_so_it_is_not_read_twice(ctx):
    context, root = ctx
    store.send_message(root, "only once")
    assert "only once" in _text(R.handle_relay_tool("relay.check", {}, ctx=context))
    follow_up = _text(R.handle_relay_tool("relay.check", {}, ctx=context))
    assert "No queued messages" in follow_up
    assert "relay.resume" in follow_up


def test_status_busy_and_resume_expose_durable_fresh_session_work(ctx):
    import json

    context, root = ctx
    sent = store.send_message(root, "canonical daemon packet", meta={"kind": "repair"})
    status = json.loads(_text(R.handle_relay_tool("relay.status", {}, ctx=context)))
    assert status["queued_depth"] == 1
    assert status["repair_depth"] == 1
    assert status["agent_polling"] is False

    claimed_text = _text(
        R.handle_relay_tool(
            "relay.check", {"session_id": "arena-session-1"}, ctx=context
        )
    )
    assert sent.id in claimed_text
    assert "relay.busy" in claimed_text

    resumed_text = _text(
        R.handle_relay_tool(
            "relay.resume", {"message_id": sent.id}, ctx=context
        )
    )
    assert "canonical daemon packet" in resumed_text
    assert "not conversation memory" in resumed_text

    busy_text = _text(
        R.handle_relay_tool(
            "relay.busy",
            {
                "message_id": sent.id,
                "session_id": "arena-session-2",
                "kind": "repair",
            },
            ctx=context,
        )
    )
    assert "arena-session-2" in busy_text
    busy_status = json.loads(_text(R.handle_relay_tool("relay.status", {}, ctx=context)))
    assert busy_status["agent_polling"] is True
    assert busy_status["last_poll_age_s"] is not None
    assert busy_status["busy_depth"] == 1
    assert busy_status["messages"][0]["claimed_by"] == "arena-session-2"
    assert busy_status["messages"][0]["kind"] == "repair"

    R.handle_relay_tool(
        "relay.reply", {"in_reply_to": sent.id, "body": "accepted"}, ctx=context
    )
    final_status = json.loads(_text(R.handle_relay_tool("relay.status", {}, ctx=context)))
    assert final_status["replied_depth"] == 1
    assert final_status["outstanding_depth"] == 0
    assert "No unfinished" in _text(
        R.handle_relay_tool("relay.resume", {}, ctx=context)
    )


def test_busy_requires_a_claimed_message_id(ctx):
    context, _root = ctx
    result = R.handle_relay_tool(
        "relay.busy", {"message_id": "000000000000"}, ctx=context
    )
    assert result["isError"] is True
    assert "not resumable" in _text(result)


def test_reply_lands_where_the_operator_reads_it(ctx):
    context, root = ctx
    sent = store.send_message(root, "question")
    R.handle_relay_tool("relay.check", {}, ctx=context)
    R.handle_relay_tool("relay.reply",
                        {"in_reply_to": sent.id, "body": "answer"}, ctx=context)
    assert [m.body for m in store.read_replies(root, in_reply_to=sent.id)] == ["answer"]


def test_reply_without_a_target_is_a_clear_error(ctx):
    context, _root = ctx
    result = R.handle_relay_tool("relay.reply", {"body": "orphan"}, ctx=context)
    assert result["isError"] is True
    assert "in_reply_to" in _text(result)


def test_send_queues_a_question_from_the_agent(ctx):
    context, root = ctx
    text = _text(R.handle_relay_tool("relay.send", {"body": "which release?"}, ctx=context))
    assert store.inbox_depth(root) == 1
    assert "Queued" in text


def test_send_does_not_promise_the_operator_is_reading(ctx):
    """The honesty rule, carried over from HTTP and the CLI.

    An agent told "delivered" will wait for an answer that may never
    come. It has to know the message is only queued.
    """
    context, _root = ctx
    text = _text(R.handle_relay_tool("relay.send", {"body": "hello"}, ctx=context))
    lowered = text.lower()
    assert "queued" in lowered
    assert "delivered" not in lowered
    assert "nothing guarantees" in lowered or "may not be" in lowered


def test_an_empty_body_is_refused_with_a_reason(ctx):
    context, _root = ctx
    result = R.handle_relay_tool("relay.send", {"body": "   "}, ctx=context)
    assert result["isError"] is True


def test_unrelated_tool_names_are_passed_through(ctx):
    """Returning a value for a name we do not own would shadow another
    handler in the dispatch chain."""
    context, _root = ctx
    assert R.handle_relay_tool("git.status", {"path": "."}, ctx=context) is None
    assert R.handle_relay_tool("fs.read", {}, ctx=context) is None


# --------------------------------------------------------------------
# wait: bounded, and non-blocking by default.
# --------------------------------------------------------------------

def test_check_does_not_block_by_default(ctx):
    """A tool that costs 25s per call is a tool the agent stops calling."""
    import time as _time

    context, _root = ctx
    started = _time.monotonic()
    R.handle_relay_tool("relay.check", {}, ctx=context)
    assert _time.monotonic() - started < 1.0


@pytest.mark.parametrize(("raw", "expected"), [
    (0, 0.0), (5, 5.0), (25, 25.0), (26, R.MAX_WAIT_S),
    (99999, R.MAX_WAIT_S), (-5, 0.0), ("abc", 0.0), (None, 0.0),
    (float("inf"), R.MAX_WAIT_S), (float("nan"), 0.0),
])
def test_wait_is_clamped(raw, expected):
    assert R._clamp_wait(raw) == expected


def test_the_mcp_cap_matches_the_http_cap():
    """Two different numbers would mean two different behaviours for the
    same operator action depending on which surface was used."""
    from arena.relay import handlers

    assert R.MAX_WAIT_S == handlers.MAX_WAIT_S


# --------------------------------------------------------------------
# Registration -- a tool nobody lists is a tool nobody calls.
# --------------------------------------------------------------------

def test_all_lifecycle_tools_are_in_the_registry():
    from arena.mcp.tool_registry import MCP_TOOLS

    names = {t["name"] for t in MCP_TOOLS}
    assert {
        "relay.busy",
        "relay.check",
        "relay.reply",
        "relay.resume",
        "relay.send",
        "relay.status",
    } <= names


def test_the_dispatcher_routes_relay_names():
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1]
    tools_py = (repo / "arena" / "mcp" / "tools.py").read_text(encoding="utf-8")
    assert "handle_relay_tool" in tools_py, (
        "the tools are advertised but nothing dispatches them"
    )


def test_the_schemas_are_closed_and_declare_their_requirements():
    """`additionalProperties: false` is a catalogue-wide invariant here."""
    for tool in R.RELAY_MCP_TOOLS:
        schema = tool["inputSchema"]
        assert schema.get("additionalProperties") is False, tool["name"]
        assert "required" in schema, tool["name"]
        for key in schema.get("required", []):
            assert key in schema["properties"], (tool["name"], key)


def test_the_descriptions_tell_the_agent_when_to_call_check():
    """A tool the agent does not know to reach for is dead weight."""
    check = next(t for t in R.RELAY_MCP_TOOLS if t["name"] == "relay.check")
    text = check["description"].lower()
    assert "non-blocking" in text or "cheap" in text
    assert "between steps" in text


def test_agents_md_tells_the_agent_to_check_the_mailbox():
    """The tool existing is not enough; the habit has to be written down."""
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1]
    guide = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "relay.check" in guide
    assert "silence as agreement" in guide, (
        "the guide must say that an unanswered message is not approval"
    )


def test_the_wiring_actually_passes_relay_root():
    """Sabotage found the gap: deleting the wiring line broke nothing.

    Every test above builds its own context, so none of them notice that
    the real bridge never supplies `relay_root` -- the tools would raise
    at runtime on the operator's machine while the suite stayed green.
    That is the same shape as a handler nobody routed to.
    """
    import ast
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1]
    source = (repo / "arena" / "wiring" / "mcp_task_runtime.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "McpToolContext"
    ]
    assert calls, "McpToolContext is no longer constructed here"
    for call in calls:
        names = {kw.arg for kw in call.keywords}
        assert "relay_root" in names, (
            "McpToolContext is built without relay_root, so relay.check "
            "will raise on a real bridge"
        )


def test_mcp_and_http_resolve_the_same_directory():
    """One mailbox, three surfaces.

    Both wirings must point at ROOT_AGENT/relay. When they diverged, a
    Dashboard message was invisible to relay.check and both halves looked
    healthy -- the reason the fallback was removed.
    """
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1] / "arena" / "wiring"
    mcp = (repo / "mcp_task_runtime.py").read_text(encoding="utf-8")
    http = (repo / "tasks_skills_resources_registries.py").read_text(
        encoding="utf-8")
    needle = 'g["ROOT_AGENT"] / "relay"'
    assert needle in mcp, "MCP relay_root does not point at ROOT_AGENT/relay"
    assert needle in http, "HTTP relay_root does not point at ROOT_AGENT/relay"

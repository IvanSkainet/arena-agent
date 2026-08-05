"""A third-party MCP server must not be able to grow this process.

`arena/mcp_client/client.py` starts external MCP servers -- `npx
some-server`, `uvx another` -- and reads their stdout on a background
thread. Bug #59: neither the line length nor the queue depth was bounded.

    self._stdout_q: queue.Queue[str | None] = queue.Queue()   # unbounded
    for line in self.proc.stdout:
        self._stdout_q.put(line)                              # unbounded

Measured with a stub that answers `initialize` and then streams 100 KB
lines: RSS 13 MB -> 1433 MB in four seconds, 14,933 lines queued. With
the bounds in place the same stub costs ~96 MB and the queue stops at
its ceiling.

The likely cause is not malice. A server that accidentally writes its
debug log to stdout instead of stderr does exactly this, and the bridge
-- not the misbehaving server -- is what dies. Whoever debugs that sees
the bridge run out of memory and blames the bridge.

Dropping is deliberate rather than truncating: a 4 MB+ "JSON-RPC frame"
cut in half is invalid JSON that the parser skips anyway, so keeping a
fragment would only make the logs less honest. When the queue is full
the OLDEST line goes, because a caller waiting on a response `id` needs
the newest output, not the backlog.

Sabotage record (mandatory per AGENTS.md):
  1. `queue.Queue()` unbounded again
     -> test_a_flooding_server_does_not_grow_the_queue fails.
  2. removing the `_MAX_LINE_CHARS` check
     -> test_an_oversized_line_is_dropped fails.
  3. dropping the newest instead of the oldest on overflow
     -> test_the_newest_line_survives_an_overflow fails.
"""
from __future__ import annotations

import queue
import sys
import textwrap

import pytest

from arena.mcp_client import client as mcp


@pytest.fixture()
def allow_python(monkeypatch):
    """Let the tests spawn `python3` as if it were an MCP server."""
    monkeypatch.setattr(
        mcp, "ALLOWED_COMMANDS",
        tuple(set(mcp.ALLOWED_COMMANDS) | {"python3", "python"}))
    return sys.executable


def _server(tmp_path, body: str):
    script = tmp_path / "server.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(script)


_INIT_REPLY = (
    '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26",'
    '"capabilities":{},"serverInfo":{"name":"stub","version":"1"}}}'
)


# ---------------------------------------------------------------------------
# The bounds themselves, tested on the queue rather than a live process.
# ---------------------------------------------------------------------------

def test_the_queue_is_bounded():
    """An unbounded queue is the bug; assert the constructor changed."""
    client = mcp.McpStdioClient("python3", [])
    assert client._stdout_q.maxsize == mcp._STDOUT_QUEUE_DEPTH
    assert 0 < mcp._STDOUT_QUEUE_DEPTH <= 10_000


def test_the_line_ceiling_is_generous_but_finite():
    """Real tool output can be large; the ceiling must not clip it.

    A limit small enough to truncate ordinary `tools/list` responses
    would get raised in a hurry and probably removed.
    """
    assert 1_000_000 <= mcp._MAX_LINE_CHARS <= 64 * 1024 * 1024


# ---------------------------------------------------------------------------
# End to end against a real child process.
# ---------------------------------------------------------------------------

def test_a_flooding_server_does_not_grow_the_queue(tmp_path, allow_python):
    """The original repro, shrunk to run fast."""
    script = _server(tmp_path, f'''
        import sys
        sys.stdin.readline()
        sys.stdout.write({_INIT_REPLY!r} + "\\n")
        sys.stdout.flush()
        chunk = "y" * 10_000
        for _ in range(20_000):
            sys.stdout.write(chunk + "\\n")
        sys.stdout.flush()
    ''')

    client = mcp.McpStdioClient("python3", [script])
    try:
        client.start(timeout=30)
        import time
        time.sleep(1.5)
        depth = client._stdout_q.qsize()
    finally:
        client.stop()

    assert depth <= mcp._STDOUT_QUEUE_DEPTH, (
        f"{depth} lines queued; the ceiling is {mcp._STDOUT_QUEUE_DEPTH}. "
        "An external server can grow this process without limit."
    )


def test_an_oversized_line_is_dropped(tmp_path, allow_python):
    """A frame past the ceiling must not reach the queue at all."""
    oversized = mcp._MAX_LINE_CHARS + 1000
    script = _server(tmp_path, f'''
        import sys
        sys.stdin.readline()
        sys.stdout.write({_INIT_REPLY!r} + "\\n")
        sys.stdout.flush()
        sys.stdout.write("z" * {oversized} + "\\n")
        sys.stdout.flush()
        import time
        time.sleep(5)
    ''')

    client = mcp.McpStdioClient("python3", [script])
    try:
        client.start(timeout=30)
        import time
        time.sleep(1.0)
        queued = []
        while True:
            try:
                queued.append(client._stdout_q.get_nowait())
            except queue.Empty:
                break
    finally:
        client.stop()

    for line in queued:
        if line is None:
            continue
        assert len(line) <= mcp._MAX_LINE_CHARS, (
            f"a {len(line)}-char line reached the queue"
        )


def test_a_well_behaved_server_still_works_end_to_end(tmp_path, allow_python):
    """A guard that breaks the normal path is a guard someone removes."""
    script = _server(tmp_path, '''
        import json, sys
        for line in sys.stdin:
            try:
                msg = json.loads(line)
            except Exception:
                continue
            method, rid = msg.get("method"), msg.get("id")
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {},
                          "serverInfo": {"name": "good", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": "echo", "description": "d",
                                     "inputSchema": {"type": "object"}}]}
            elif method == "tools/call":
                result = {"content": [{"type": "text", "text": "pong"}]}
            else:
                continue
            if rid is not None:
                sys.stdout.write(json.dumps(
                    {"jsonrpc": "2.0", "id": rid, "result": result}) + "\\n")
                sys.stdout.flush()
    ''')

    client = mcp.McpStdioClient("python3", [script])
    try:
        client.start(timeout=30)
        tools = client.list_tools(timeout=30)
        called = client.call_tool("echo", {"x": 1}, timeout=30)
    finally:
        client.stop()

    assert [t["name"] for t in tools] == ["echo"]
    assert called["content"][0]["text"] == "pong"


def test_a_large_but_legal_response_is_not_dropped(tmp_path, allow_python):
    """Tool output of a megabyte is normal and must survive."""
    script = _server(tmp_path, '''
        import json, sys
        for line in sys.stdin:
            try:
                msg = json.loads(line)
            except Exception:
                continue
            method, rid = msg.get("method"), msg.get("id")
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {},
                          "serverInfo": {"name": "big", "version": "1"}}
            elif method == "tools/call":
                result = {"content": [{"type": "text", "text": "Q" * 1_000_000}]}
            else:
                continue
            if rid is not None:
                sys.stdout.write(json.dumps(
                    {"jsonrpc": "2.0", "id": rid, "result": result}) + "\\n")
                sys.stdout.flush()
    ''')

    client = mcp.McpStdioClient("python3", [script])
    try:
        client.start(timeout=30)
        called = client.call_tool("big", {}, timeout=30)
    finally:
        client.stop()

    assert len(called["content"][0]["text"]) == 1_000_000


# ---------------------------------------------------------------------------
# Overflow policy.
# ---------------------------------------------------------------------------

def test_the_newest_line_survives_an_overflow():
    """A caller waits for its own response id -- the newest line matters.

    Dropping the newest on overflow would mean a full queue permanently
    hides every future reply, turning a chatty server into a hang.
    """
    client = mcp.McpStdioClient("python3", [])
    for index in range(mcp._STDOUT_QUEUE_DEPTH):
        client._stdout_q.put_nowait(f"old-{index}\n")

    # Mirror what the reader does when put_nowait raises Full.
    line = "the-newest\n"
    try:
        client._stdout_q.put_nowait(line)
    except queue.Full:
        client._stdout_q.get_nowait()
        client._stdout_q.put_nowait(line)

    drained = []
    while True:
        try:
            drained.append(client._stdout_q.get_nowait())
        except queue.Empty:
            break

    assert drained[-1] == "the-newest\n"
    assert len(drained) == mcp._STDOUT_QUEUE_DEPTH


def test_eof_reaches_a_waiting_caller_even_when_the_queue_is_full():
    """The None sentinel is how `request()` learns the server died.

    If a full queue swallowed it, a caller would block until its timeout
    instead of getting "server closed the connection".
    """
    client = mcp.McpStdioClient("python3", [])
    for index in range(mcp._STDOUT_QUEUE_DEPTH):
        client._stdout_q.put_nowait(f"line-{index}\n")

    try:
        client._stdout_q.put_nowait(None)
    except queue.Full:
        client._stdout_q.get_nowait()
        client._stdout_q.put_nowait(None)

    drained = []
    while True:
        try:
            drained.append(client._stdout_q.get_nowait())
        except queue.Empty:
            break

    assert None in drained

"""Shutting down the bridge must stop the recorder running on the phone.

Bug #60. `arena/mobile/mirror.py` has a `stop_all()`, `arena/mobile/
__init__.py` re-exports it as `mirror_stop_all`, and mirror.py even
contains the sentence "`stop_all()` on bridge shutdown had the same
problem" -- written by me, one cycle earlier, while assuming a caller
that did not exist. Nothing called it. Anywhere.

Each live mirror session holds a `screenrecord` process **on the phone**.
Killing the bridge left it recording: filling device storage, with no
local process left that knows how to stop it. Restarting the bridge does
not help either -- `get_or_start` creates a new session rather than
adopting the orphan.

Verified before the fix: a session with a stubbed long-running
screenrecord survived `on_cleanup` completely untouched.

Both paths matter. `on_cleanup` is aiohttp's orderly shutdown;
`signal_handler` ends with `os._exit(0)` on a five-second timer and on
SIGTERM may run without cleanup finishing. The browser was already torn
down in both places for exactly that reason.

These tests assert the CALL, not the existence of the function -- the
function existed the whole time the bug did.

Sabotage record (mandatory per AGENTS.md):
  1. removing the stop_all call from on_cleanup
     -> test_on_cleanup_stops_mirror_sessions fails.
  2. removing it from signal_handler
     -> test_signal_handler_stops_mirror_sessions fails.
  3. making stop_all a no-op
     -> test_stop_all_actually_ends_the_session fails.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import sys

import pytest

from arena.mobile import mirror

LIFECYCLE = pathlib.Path(__file__).resolve().parents[1] / "arena" / "lifecycle.py"


def _functions_calling_stop_all() -> set[str]:
    """Names of top-level-ish functions in lifecycle.py that call it.

    Parsed rather than grepped: a mention in a comment or docstring is
    exactly what fooled me last time, and this file now contains several.
    """
    tree = ast.parse(LIFECYCLE.read_text(encoding="utf-8"))
    callers: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.stack: list[str] = []

        def _walk_function(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = _walk_function
        visit_AsyncFunctionDef = _walk_function

        def visit_Call(self, node):
            target = node.func
            name = getattr(target, "id", None) or getattr(target, "attr", None)
            if name in {"stop_all", "_mirror_stop_all", "mirror_stop_all"}:
                if self.stack:
                    callers.add(self.stack[-1])
            self.generic_visit(node)

    Visitor().visit(tree)
    return callers


# ---------------------------------------------------------------------------
# The call sites.
# ---------------------------------------------------------------------------

def test_on_cleanup_stops_mirror_sessions():
    assert "on_cleanup" in _functions_calling_stop_all(), (
        "on_cleanup does not stop mirror sessions; a screenrecord keeps "
        "running on the phone after the bridge exits"
    )


def test_signal_handler_stops_mirror_sessions():
    """SIGTERM may not let aiohttp's cleanup finish before os._exit(0)."""
    assert "signal_handler" in _functions_calling_stop_all(), (
        "signal_handler does not stop mirror sessions, and it ends with "
        "os._exit(0) on a timer -- on_cleanup is not guaranteed to run"
    )


def test_the_teardown_matches_how_the_browser_is_handled():
    """The browser is torn down in both paths; so must the recorder be.

    An asymmetry here is how the gap appeared in the first place.
    """
    source = LIFECYCLE.read_text(encoding="utf-8")
    callers = _functions_calling_stop_all()
    assert {"on_cleanup", "signal_handler"} <= callers
    assert source.count("_browser_proc") >= 2


# ---------------------------------------------------------------------------
# And the function has to work.
# ---------------------------------------------------------------------------

@pytest.fixture()
def stub_mirror(monkeypatch):
    monkeypatch.setattr(mirror, "find_adb", lambda: sys.executable)
    stub = ("import sys, time; sys.stdout.buffer.write(b'x'); "
            "sys.stdout.flush(); time.sleep(30)")
    monkeypatch.setattr(
        mirror, "_screenrecord_cmd",
        lambda serial, size, bit_rate: [sys.executable, "-c", stub])
    monkeypatch.setattr(mirror, "_SESSIONS", {}, raising=False)
    yield
    for session in list(mirror._SESSIONS.values()):
        session.stop_event.set()


def test_stop_all_actually_ends_the_session(stub_mirror):
    """Calling it must do something -- a no-op would pass the AST checks."""
    async def _run():
        session = mirror.get_or_start("emulator-5554")
        session.add_subscriber()
        await asyncio.sleep(0.4)
        started = session.segments_started > 0

        mirror.stop_all()
        await asyncio.sleep(1.0)

        return started, session.reader_task.done(), len(mirror._SESSIONS)

    started, stopped, remaining = asyncio.run(_run())

    assert started, "the pipeline never reached screenrecord"
    assert stopped, "stop_all did not end the pipeline"
    assert remaining == 0, "the session stayed in the registry"


def test_stop_all_is_safe_with_no_sessions(stub_mirror):
    """Shutdown runs it unconditionally, including on an idle bridge."""
    mirror.stop_all()
    assert len(mirror._SESSIONS) == 0


def test_stop_all_handles_several_sessions(stub_mirror):
    async def _run():
        for serial in ("phone-a", "phone-b", "phone-c"):
            mirror.get_or_start(serial).add_subscriber()
        await asyncio.sleep(0.4)
        before = len(mirror._SESSIONS)

        mirror.stop_all()
        await asyncio.sleep(1.0)
        return before, len(mirror._SESSIONS)

    before, after = asyncio.run(_run())
    assert before == 3
    assert after == 0

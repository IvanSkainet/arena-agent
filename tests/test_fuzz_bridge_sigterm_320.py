"""SIGTERM must stop the fuzz bridge without raising from a random frame (#320).

`scripts/serve_bridge_for_fuzzing.py` used to install a SIGTERM handler
that raised `KeyboardInterrupt`. The intent was right -- SIGTERM's default
action skips every `finally`, so each run leaked its temporary workspace
-- but a Python signal handler runs between two arbitrary bytecodes, in
whatever the interpreter happens to be doing. With the collector busy that
is often a weakref callback, and the exception then unwinds the frame the
GC was passing through rather than the one the author meant:

    File ".../_weakrefset.py", line ..., in _remove
    KeyboardInterrupt: signal 15

Measured while reproducing this: SIGTERM delivered from another thread
while the main thread churned weakrefs surfaced inside
`_weakrefset.py::_remove` in 6 runs out of 14. It reddened
`test_api_fuzz_gate_258.py` intermittently -- not a flaky test, a race in
the handler that the test was catching.

The loop now owns the signal while it is running, so the wakeup lands
where the loop chose. These tests pin the properties that made the change
worth making, not the mechanism: a different implementation that keeps
them is free to replace it.
"""
from __future__ import annotations

import ast
import glob
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = REPO_ROOT / "scripts" / "serve_bridge_for_fuzzing.py"
WORKSPACE_GLOB = str(Path(tempfile.gettempdir()) / "fuzz-root-*")

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="SIGTERM delivery and add_signal_handler are POSIX-only here")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start(port: int) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, str(SERVER_PATH), "--port", str(port)],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "ARENA_FUZZ_TOKEN": "sigterm-probe-320",
             "PYTHONDONTWRITEBYTECODE": "1"})


def _wait_until_listening(proc: subprocess.Popen[str], port: int) -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"the bridge exited: {proc.communicate()[0]}")
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    proc.kill()
    raise AssertionError("the bridge did not start within 60s")


def _stop_and_read(proc: subprocess.Popen[str]) -> str:
    proc.send_signal(signal.SIGTERM)
    try:
        return proc.communicate(timeout=60)[0]
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError(
            f"SIGTERM did not stop the bridge: {proc.communicate()[0]}"
        ) from None


def _function_named(tree: ast.AST, name: str) -> ast.AST | None:
    """The `def` or `async def` called `name`, or None.

    Pulled out of the structural test: the two inline generator
    expressions it replaces carried most of that test's complexity
    (CC 12, over CodeScene's threshold of 9) without carrying any of
    its meaning.
    """
    wanted = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if isinstance(node, wanted) and node.name == name:
            return node
    return None


def test_the_running_loop_owns_sigterm_rather_than_a_raising_handler() -> None:
    """The deterministic guard, and the one that matters most.

    The runtime test below only catches the old handler when the
    interrupt happens to land somewhere visible -- restoring the raising
    handler failed it 1 run in 10, because the race needs the collector
    to be mid-callback. That is the same trap as #358: a real defect
    behind a probabilistic assertion reads as "flaky test" and gets
    rerun until it passes.

    The mechanism is checkable exactly, so it is checked exactly: while
    the loop runs, SIGTERM must be delivered through
    `loop.add_signal_handler`, and `_serve` must wait on the event that
    handler sets instead of sleeping forever and relying on an exception
    to break out.
    """
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    serve = _function_named(tree, "_serve")
    assert serve is not None, "_serve is gone"

    manager = _function_named(tree, "_loop_owns_sigterm")
    assert manager is not None, (
        "nothing hands SIGTERM to the loop; a raising handler is back")
    assert "add_signal_handler" in ast.dump(manager), ast.dump(manager)

    serve_body = ast.dump(serve)
    assert "IDLE_SLEEP_S" not in serve_body, (
        "_serve still sleeps forever, so only an exception can end it")

    # The guard has to be *entered*, not merely mentioned: substituting
    # `with _loop_owns_sigterm(stop):` for `if True:` leaves the name in
    # the file (the import, the def) and passed a plain text check.
    entered = [
        item.context_expr for node in ast.walk(serve)
        if isinstance(node, (ast.With, ast.AsyncWith))
        for item in node.items
    ]
    assert any(isinstance(call, ast.Call)
               and getattr(call.func, "id", "") == "_loop_owns_sigterm"
               for call in entered), (
        "_serve never enters _loop_owns_sigterm, so the signal is still "
        "handled by whatever was installed before it")


def test_sigterm_while_serving_does_not_raise_through_the_interpreter() -> None:
    """The same defect observed from outside the process.

    Weaker than the structural check above -- the interrupt has to land
    somewhere that shows up -- but it is the only one that proves the
    real binary behaves, rather than that the source reads correctly.

    A `KeyboardInterrupt` in the log means the signal was turned into an
    exception at whatever bytecode boundary the interpreter had reached.
    That is what put tracebacks in `_weakrefset.py` into CI logs.
    """
    port = _free_port()
    proc = _start(port)
    try:
        _wait_until_listening(proc, port)
    except BaseException:
        proc.kill()
        proc.communicate()
        raise
    log = _stop_and_read(proc)

    assert proc.returncode == 0, log
    assert "KeyboardInterrupt" not in log, (
        "SIGTERM was raised as an exception from an arbitrary frame:\n" + log)
    assert "Traceback" not in log, log


def test_sigterm_while_serving_still_removes_the_workspace() -> None:
    """The reason the handler existed at all.

    The control for the test above: a bridge that ignores SIGTERM also
    logs no traceback. The workspace has to be gone too, which is only
    true if the `finally` actually ran.
    """
    before = set(glob.glob(WORKSPACE_GLOB))
    port = _free_port()
    proc = _start(port)
    # An assertion between start and stop would otherwise leave a live
    # bridge holding the port and its workspace, and the next test's
    # `_free_port` can hand out that same port (review).
    try:
        _wait_until_listening(proc, port)
        created = sorted(set(glob.glob(WORKSPACE_GLOB)) - before)
        assert len(created) == 1, f"expected one workspace, got {created}"
    except BaseException:
        proc.kill()
        proc.communicate()
        raise

    log = _stop_and_read(proc)

    assert sorted(set(glob.glob(WORKSPACE_GLOB)) - before) == [], (
        "SIGTERM left the workspace behind:\n" + log)
    assert "bridge stopped" in log, (
        "a clean stop must say so, or a crash that exits 0 reads the same:\n"
        + log)


def test_the_previous_handler_is_restored_when_the_loop_gives_the_signal_back(
        ) -> None:
    """`remove_signal_handler` alone would reopen the hole after the loop.

    `main`'s `finally` -- the one that deletes the workspace -- runs after
    `asyncio.run` returns. `loop.remove_signal_handler` restores `SIG_DFL`,
    so a SIGTERM arriving in that window kills the process outright:
    measured rc=-15, workspace leaked. The teardown therefore reinstates
    the handler that was there before, and this checks the source says so
    rather than trusting a comment.
    """
    source = SERVER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    manager = _function_named(tree, "_loop_owns_sigterm")
    assert manager is not None, "the signal-ownership helper is gone"

    body = ast.dump(manager)
    assert "remove_signal_handler" in body, body
    # The restore has to be there as well, not just the removal.
    assert body.count("signal") >= 2 and "getsignal" in ast.dump(tree), (
        "the previous SIGTERM handler is never captured for restoration")


def _wait_for_workspace(proc: subprocess.Popen[str],
                        before: set[str]) -> list[str]:
    """Block until the bridge's workspace exists, and return it.

    Polled rather than slept for: fixed delays mostly fired before the
    directory existed, so the caller asserted nothing (review). A bridge
    that dies on its own never received the signal, so that is an
    outright failure instead of a quiet "attempt made" -- otherwise a
    startup crash passes for a passing test.
    """
    deadline = time.time() + 60
    while time.time() < deadline:
        created = sorted(set(glob.glob(WORKSPACE_GLOB)) - before)
        if created:
            return created
        if proc.poll() is not None:
            raise AssertionError(
                "the bridge exited before it created a workspace: "
                f"{proc.communicate()[0]}")
        time.sleep(0.005)
    return []


def test_a_kill_before_the_loop_exists_still_cleans_up() -> None:
    """The window `add_signal_handler` cannot cover.

    The workspace is created, prepared and the app built before
    `asyncio.run`. A signal there is still handled by the raising handler
    installed in `main`, and that is deliberate: it unwinds into the
    try/finally the cleanup lives in. The window is narrow, so each
    attempt polls for the workspace and signals the instant it appears
    rather than guessing a delay -- fixed delays mostly fired before the
    directory existed and asserted nothing (review).
    """
    exercised = 0
    for _ in range(3):
        before = set(glob.glob(WORKSPACE_GLOB))
        proc = _start(_free_port())
        # Fixed delays were wrong (review): 0.05s and 0.1s land while the
        # interpreter is still importing, before `main` has created
        # anything, so the assertion below held no matter what the
        # cleanup did. Poll for the directory instead and signal the
        # moment it exists -- that is the window this test is named for,
        # and it is narrow because the loop starts right after.
        created = _wait_for_workspace(proc, before)
        proc.send_signal(signal.SIGTERM)
        try:
            log = proc.communicate(timeout=60)[0]
        except subprocess.TimeoutExpired:
            # Seen once on a macos-latest runner and not reproducible in
            # 15+15 local attempts, including with the startup gap held
            # open artificially. The signal is delivered the instant the
            # directory appears, so on a slow box it can arrive while
            # `main` is still between the workspace and the loop -- a
            # genuinely narrow window that this test aims at on purpose.
            # A second SIGTERM is sent rather than SIGKILL so the cleanup
            # still has its chance, and the workspace assertion below
            # still has to hold: a leaked directory fails either way,
            # which is what the test is for. Only the timing is tolerated.
            proc.send_signal(signal.SIGTERM)
            try:
                log = proc.communicate(timeout=30)[0]
            except subprocess.TimeoutExpired:
                proc.kill()
                raise AssertionError(
                    "the bridge ignored two SIGTERMs") from None

        left = sorted(set(glob.glob(WORKSPACE_GLOB)) - before)
        assert left == [], (
            f"a SIGTERM during startup leaked a workspace: {left}\n{log}")
        exercised += bool(created)

    assert exercised, (
        "every attempt signalled before the workspace existed, so nothing "
        "about the pre-loop cleanup was exercised")

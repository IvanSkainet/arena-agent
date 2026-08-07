"""The bridge must die when asked, even with a WebSocket attached.

Bug #71, surfaced by CI as an error nobody had looked at twice:

    ERROR at teardown of test_dashboard_survives_a_reload
    Failed: bridge ignored SIGTERM for 30s and had to be SIGKILLed (rc=-9)

Ten tests passed and one teardown errored, so the run was red for a
reason unrelated to any assertion -- easy to file under "flaky CI". It
was not flaky. Two real defects stacked:

1. `web.run_app(handle_signals=True)` is the default, and it installs its
   own SIGTERM/SIGINT handlers, **overwriting** the ones `serve()`
   registers a few lines earlier. The bridge's handler is what stops the
   watchdog, terminates the CDP browser, calls `mirror.stop_all()` (bug
   #60) and arms the `os._exit(0)` backstop on a 5s timer. None of it
   ran.
2. aiohttp's `shutdown_timeout` defaults to **60 seconds** and it waits
   for open WebSockets to close. `41-live-charts.js` keeps one open, so
   any bridge that had served the dashboard sat there for a minute.

Reproduced by execution before the fix: with a WebSocket attached the
process ignored SIGTERM past 40s; with none it exited in 0.1s. That gap
is exactly why this only ever appeared in the browser E2E job -- the
other suites never open one.

Consequences beyond CI: `POST /v1/restart` and the auto-update restart
path both rely on the process actually leaving, and a service manager
that sends SIGTERM and waits will SIGKILL the bridge mid-write.
"""
from __future__ import annotations

import ast
import os
import pathlib
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="POSIX signal semantics; Windows uses a different path"
)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _boot(port: int, token: str) -> subprocess.Popen:
    proc = subprocess.Popen(  # nosec B603 -- fixed argv, no shell
        [sys.executable, "unified_bridge.py", "serve", "--bind", "127.0.0.1",
         "--port", str(port), "--token", token, "--root", str(REPO)],
        cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            pytest.fail(f"bridge exited during startup: {out[-2000:]}")
        try:
            with urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{port}/health", timeout=1
            ) as resp:
                if resp.status == 200:
                    return proc
        except (OSError, urllib.error.HTTPError):
            time.sleep(0.25)
    proc.kill()
    pytest.fail("bridge did not become healthy within 60s")


def _terminate(proc: subprocess.Popen, budget: float) -> float:
    started = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=budget)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return float("inf")
    return time.monotonic() - started


@pytest.mark.timeout(180)
def test_sigterm_stops_the_bridge_promptly():
    port, token = _free_port(), "e2e-" + secrets.token_urlsafe(16)
    proc = _boot(port, token)
    elapsed = _terminate(proc, 25)
    assert elapsed != float("inf"), "bridge ignored SIGTERM with no clients"
    assert elapsed < 15, f"took {elapsed:.1f}s to stop"


@pytest.mark.timeout(240)
def test_sigterm_stops_the_bridge_with_a_websocket_attached():
    """The actual bug. The dashboard always has one of these open."""
    websockets = pytest.importorskip("websockets")
    import asyncio

    port, token = _free_port(), "e2e-" + secrets.token_urlsafe(16)
    proc = _boot(port, token)
    connected = threading.Event()

    async def _hold():
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/ws?token={token}"
            ):
                connected.set()
                await asyncio.sleep(120)
        except Exception:  # nosec B110 -- the test asserts on shutdown, not this
            connected.set()

    threading.Thread(target=lambda: asyncio.run(_hold()), daemon=True).start()
    connected.wait(timeout=20)
    time.sleep(2)

    elapsed = _terminate(proc, 25)
    assert elapsed != float("inf"), (
        "bridge ignored SIGTERM while a WebSocket was open -- this is the "
        "bug: aiohttp's default 60s shutdown_timeout waits for it"
    )
    assert elapsed < 15, (
        f"took {elapsed:.1f}s with a WebSocket attached; a service manager "
        f"would SIGKILL it mid-write"
    )


# --------------------------------------------------------------------
# Static guards: the two settings that caused it must not drift back.
# --------------------------------------------------------------------

def _run_app_call() -> ast.Call:
    tree = ast.parse((REPO / "arena" / "cli.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run_app"):
            return node
    pytest.fail("web.run_app call not found in arena/cli.py")


def test_run_app_does_not_take_over_signal_handling():
    """`handle_signals=True` silently replaces the bridge's own handler.

    That handler is not decoration: it stops the watchdog, kills the CDP
    browser and calls mirror.stop_all(), which is bug #60 -- a recorder
    left running on the operator's phone.
    """
    kwargs = {kw.arg: kw.value for kw in _run_app_call().keywords}
    assert "handle_signals" in kwargs, (
        "run_app defaults to handle_signals=True and will overwrite the "
        "handler registered in serve()"
    )
    value = kwargs["handle_signals"]
    assert isinstance(value, ast.Constant) and value.value is False, (
        "handle_signals must be False so the bridge's own handler survives"
    )


def test_shutdown_timeout_is_bounded_well_below_a_service_manager_kill():
    """systemd's default TimeoutStopSec is 90s; ours must be far under."""
    kwargs = {kw.arg: kw.value for kw in _run_app_call().keywords}
    assert "shutdown_timeout" in kwargs, (
        "aiohttp defaults to 60s and waits for open WebSockets"
    )
    value = kwargs["shutdown_timeout"]
    assert isinstance(value, ast.Constant), value
    assert 0 < float(value.value) <= 10, (
        f"shutdown_timeout={value.value}; a client that has not finished "
        f"within a few seconds is not going to"
    )


def test_the_signal_handler_is_still_registered_before_run_app():
    """Order matters: registering after run_app would never execute."""
    source = (REPO / "arena" / "cli.py").read_text(encoding="utf-8")
    register_at = source.index("signal.signal(sig, ctx.signal_handler)")
    run_at = source.index("web.run_app(")
    assert register_at < run_at

"""The live mirror must survive the subscriber arriving a moment late.

Bug #49, reported by Ivan as "live in mobile doesn't work at all". It is
a race, which is why it looked intermittent and why nothing caught it.

`get_or_start` schedules `_pump_pipeline`, and only *then* does the
caller subscribe. The pipeline's main loop is

    while not stop_event.is_set() and session.has_subscribers():

so whoever won that race decided whether the mirror worked:

  * subscribe before the loop's first evaluation -> it streams;
  * lose by a few milliseconds -> `has_subscribers()` is False, the loop
    exits immediately, and the `finally` block pops the session out of
    `_SESSIONS`. The browser is left holding a dead session, and a retry
    finds nothing in the registry either.

On the WebSocket path there is an `await ws.prepare(request)` between
the two, so the subscriber lost that race essentially every time.

Measured before the fix, with a stub screenrecord:
    subscribe after 0.30s -> reader_task.done() is True, session gone
    subscribe immediately -> reader_task alive

The fix is an explicit handshake: the pipeline waits on
`first_subscriber` instead of guessing, with a timeout so a client that
dies mid-handshake cannot leave screenrecord running on the phone.

Sabotage record (mandatory per AGENTS.md):
  1. removing the `first_subscriber.wait()` block
     -> test_pipeline_survives_a_late_subscriber fails.
  2. removing `first_subscriber.set()` from `add_subscriber`
     -> test_pipeline_survives_a_late_subscriber fails (times out).
  3. dropping the `_SESSIONS.pop` from the timeout path
     -> test_abandoned_session_is_not_left_in_the_registry fails.

These run through `asyncio.run` rather than pytest-asyncio, matching the
convention in the rest of tests/ (the plugin is not a dependency).
"""
from __future__ import annotations

import asyncio
import sys

import pytest

from arena.mobile import mirror


@pytest.fixture()
def stub_adb(monkeypatch):
    """Never touch a real device; screenrecord becomes a long sleep."""
    monkeypatch.setattr(mirror, "find_adb", lambda: sys.executable)
    # Emit a byte, then linger. `not reader_task.done()` turned out to be
    # too weak a signal on its own -- a pipeline parked in
    # `wait_for(first_subscriber)` is also "not done", so a sabotage that
    # removed `first_subscriber.set()` slipped through. Tests now assert
    # the pipeline actually reached screenrecord, via `started_reading`.
    #
    # Spawned via sys.executable rather than /bin/sh: the first version
    # of this used a shell one-liner and went red on every Windows runner
    # ("[WinError 2] The system cannot find the file specified"). A test
    # for platform-independent logic must not itself be POSIX-only.
    stub = ("import sys, time; sys.stdout.buffer.write(b'x'); "
            "sys.stdout.flush(); time.sleep(30)")
    monkeypatch.setattr(
        mirror, "_screenrecord_cmd",
        lambda serial, size, bit_rate: [sys.executable, "-c", stub])
    monkeypatch.setattr(mirror, "_SESSIONS", {}, raising=False)
    yield
    for session in list(mirror._SESSIONS.values()):
        session.stop_event.set()


def test_pipeline_survives_a_late_subscriber(stub_adb):
    """The exact reported failure: the live mirror never streams."""
    async def _run():
        session = mirror.get_or_start("emulator-5554")

        # The WebSocket upgrade happens here in production.
        await asyncio.sleep(0.30)
        alive_before = not session.reader_task.done()

        session.add_subscriber()
        await asyncio.sleep(0.40)
        alive_after = not session.reader_task.done()
        # The real property: bytes from screenrecord reached the muxer.
        # "task not finished" alone is satisfied by a pipeline still
        # parked waiting for a subscriber that will never be announced.
        streaming = session.segments_started > 0

        registered = "emulator-5554" in mirror._SESSIONS
        session.stop_event.set()
        return alive_before, alive_after, streaming, registered

    alive_before, alive_after, streaming, registered = asyncio.run(_run())

    assert alive_before, (
        "the pipeline exited before anyone could subscribe -- this is why "
        "the live mirror never worked"
    )
    assert alive_after
    assert streaming, (
        "the pipeline never started reading screenrecord after the "
        "subscriber attached"
    )
    assert registered


def test_pipeline_also_works_when_the_subscriber_is_first(stub_adb):
    """The ordering that accidentally worked must keep working."""
    async def _run():
        session = mirror.get_or_start("emulator-5554")
        session.add_subscriber()
        await asyncio.sleep(0.40)
        alive = not session.reader_task.done()
        streaming = session.segments_started > 0
        session.stop_event.set()
        return alive and streaming

    assert asyncio.run(_run())


def test_abandoned_session_is_not_left_in_the_registry(stub_adb, monkeypatch):
    """A client that dies mid-handshake must not pin a session forever.

    Without the timeout the pipeline would park on `first_subscriber`
    indefinitely, holding a screenrecord process on the phone.
    """
    monkeypatch.setattr(mirror, "_FIRST_SUBSCRIBER_TIMEOUT", 0.3)

    async def _run():
        mirror.get_or_start("emulator-5554")
        await asyncio.sleep(0.9)
        return "emulator-5554" in mirror._SESSIONS

    assert not asyncio.run(_run()), (
        "an abandoned session stayed in the registry, so the next request "
        "for this serial would attach to a pipeline nobody is feeding"
    )


def test_a_second_viewer_reuses_the_running_session(stub_adb):
    """Two browsers on one phone must not spawn two screenrecords."""
    async def _run():
        first = mirror.get_or_start("emulator-5554")
        first.add_subscriber()
        await asyncio.sleep(0.20)

        second = mirror.get_or_start("emulator-5554")
        second.add_subscriber()

        same = second is first
        count = len(first.subscribers)
        sessions = len(mirror._SESSIONS)
        first.stop_event.set()
        return same, count, sessions

    same, count, sessions = asyncio.run(_run())
    assert same
    assert count == 2
    assert sessions == 1


def test_last_viewer_leaving_stops_the_pipeline(stub_adb):
    """The flip side of the fix: it must still shut down when idle."""
    async def _run():
        session = mirror.get_or_start("emulator-5554")
        queue = session.add_subscriber()
        await asyncio.sleep(0.20)
        started = not session.reader_task.done()

        session.remove_subscriber(queue)
        session.stop_event.set()
        await asyncio.sleep(0.40)
        return started, session.reader_task.done()

    started, stopped = asyncio.run(_run())
    assert started
    assert stopped

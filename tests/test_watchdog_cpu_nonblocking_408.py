"""T73: watchdog CPU sampling preserves responsiveness and alert semantics."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest import TestCase

from arena.watchdog import runtime

CHECK = TestCase()


def test_cpu_sample_runs_off_loop_and_emits_the_measured_alert(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()
    main_thread = threading.get_ident()
    samples = []
    emitted = []
    original_sleep = asyncio.sleep

    def cpu_percent(*, interval):
        entered.set()
        released = release.wait(2)  # safety bound; progress is event-driven
        samples.append((threading.get_ident() != main_thread, interval, released))
        return 95.5

    process = SimpleNamespace(
        memory_info=lambda: SimpleNamespace(rss=1024 * 1024),
        cpu_percent=cpu_percent,
    )
    monkeypatch.setattr(runtime, "_watchdog_process", lambda: process)
    for key, value in {"alerts": [], "memory_limit_mb": 512, "cpu_limit_percent": 90,
                       "last_check": 0, "memory_mb": 0, "cpu_percent": 0}.items():
        monkeypatch.setitem(runtime.WATCHDOG_STATE, key, value)

    async def immediate_tick(_delay):
        await original_sleep(0)

    async def emit(kind, alert):
        emitted.append((kind, alert))
        raise asyncio.CancelledError  # stop after the first real sample

    async def exercise():
        monkeypatch.setattr(runtime, "asyncio", SimpleNamespace(
            **{**vars(asyncio), "sleep": immediate_tick}))
        task = asyncio.create_task(runtime.watchdog_loop(
            utc_now_fn=lambda: "test-time", emit_event_fn=emit))
        try:
            CHECK.assertTrue(await asyncio.to_thread(entered.wait, 2))
            # This coroutine must run while cpu_percent is still waiting.
            release.set()
            await asyncio.wait_for(task, 2)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())
    CHECK.assertEqual(samples, [(True, 1.0, True)])
    CHECK.assertEqual(runtime.WATCHDOG_STATE["cpu_percent"], 95.5)
    CHECK.assertEqual(runtime.WATCHDOG_STATE["memory_mb"], 1.0)
    CHECK.assertEqual(emitted, [("alert", {"type": "cpu_high", "value_pct": 95.5,
                                        "limit_pct": 90, "ts": "test-time"})])

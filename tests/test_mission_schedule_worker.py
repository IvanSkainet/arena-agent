"""Mission schedule worker runtime regressions.

v4.61.1: increase the asyncio.sleep() inside ``_run_once`` from
0.01s to 0.1s. The original value was tuned for fast Linux CI
where the executor returns in single-digit milliseconds. On
slower Windows runners the executor hadn't completed before
``task.cancel()`` ran, so ``total_ticks`` was still 0 when the
test asserted ``>= 1``. 0.1s is a 10x safety margin that still
keeps the test fast enough for the CI feedback loop.

Live-failed: v4.61.0 CI run id 30034756453 on
``windows-latest`` Python 3.10-3.14.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.resources.mission_schedule_worker import MissionScheduleWorkerContext, make_mission_schedule_worker_runtime  # noqa: E402



def test_mission_schedule_worker_state_sync_defaults():
    runtime = make_mission_schedule_worker_runtime(MissionScheduleWorkerContext(
        tick_sync=lambda data: {"ok": True, "executed": 0},
        interval_seconds=30,
        utc_now=lambda: "2026-06-23T00:00:00+00:00",
        log_info=lambda *args, **kwargs: None,
        log_error=lambda *args, **kwargs: None,
    ))
    state = runtime.state_sync()
    assert state["ok"] is True
    assert state["worker"]["interval_seconds"] == 30
    assert state["worker"]["total_ticks"] == 0



def test_mission_schedule_worker_loop_updates_state():
    calls = []
    runtime = make_mission_schedule_worker_runtime(MissionScheduleWorkerContext(
        tick_sync=lambda data: calls.append(data) or {"ok": True, "executed": 2},
        interval_seconds=0,
        utc_now=lambda: "2026-06-23T00:00:00+00:00",
        log_info=lambda *args, **kwargs: None,
        log_error=lambda *args, **kwargs: None,
    ))

    async def _run_once():
        task = asyncio.create_task(runtime.loop(None))
        # v4.61.1: 0.1s instead of 0.01s. On Windows runners
        # run_in_executor for an empty tick_sync() took up to
        # 60ms; 0.1s gives a 40ms safety margin while still
        # keeping the test under 200ms total.
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run_once())
    state = runtime.state_sync()["worker"]
    assert calls
    assert state["total_ticks"] >= 1
    assert state["total_executed"] >= 2
    assert state["last_ok"] is True

"""Background worker for recurring mission schedules."""
from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web


@dataclass(frozen=True)
class MissionScheduleWorkerContext:
    tick_sync: Callable[[dict[str, Any]], dict[str, Any]]
    interval_seconds: int
    utc_now: Callable[[], str]
    log_info: Callable[..., None]
    log_error: Callable[..., None]


@dataclass(frozen=True)
class MissionScheduleWorkerRuntime:
    state: dict[str, Any]
    state_sync: Callable[[], dict[str, Any]]
    loop: Callable[[web.Application], Any]



def make_mission_schedule_worker_runtime(ctx: MissionScheduleWorkerContext) -> MissionScheduleWorkerRuntime:
    state = {
        "enabled": True,
        "interval_seconds": int(ctx.interval_seconds or 60),
        "started_at": "",
        "last_tick_at": "",
        "last_ok": None,
        "last_executed": 0,
        "total_ticks": 0,
        "total_executed": 0,
        "last_error": "",
    }

    def _state_sync() -> dict[str, Any]:
        return {"ok": True, "worker": dict(state)}

    async def _loop(app: web.Application) -> None:
        state["started_at"] = ctx.utc_now()
        ctx.log_info("[MissionSchedules] worker started (interval=%ss)", state["interval_seconds"])
        while True:
            try:
                result = await asyncio.get_running_loop().run_in_executor(None, ctx.tick_sync, {"limit": 10, "timeout": 180})
                state["last_tick_at"] = ctx.utc_now()
                state["last_ok"] = bool(result.get("ok", False))
                state["last_executed"] = int(result.get("executed", 0) or 0)
                state["total_ticks"] += 1
                state["total_executed"] += int(result.get("executed", 0) or 0)
                state["last_error"] = "" if result.get("ok", False) else str(result.get("error", "") or "")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state["last_tick_at"] = ctx.utc_now()
                state["last_ok"] = False
                state["last_executed"] = 0
                state["total_ticks"] += 1
                state["last_error"] = str(exc)
                ctx.log_error("[MissionSchedules] worker error: %s", exc)
            await asyncio.sleep(state["interval_seconds"])

    return MissionScheduleWorkerRuntime(state=state, state_sync=_state_sync, loop=_loop)


__all__ = ["MissionScheduleWorkerContext", "MissionScheduleWorkerRuntime", "make_mission_schedule_worker_runtime"]

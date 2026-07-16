"""Handlers for watchdog status/configuration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiohttp import web

from arena.handler_context import WatchdogHandlerContext
from arena.watchdog.runtime import WATCHDOG_STATE
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class WatchdogHandlers:
    watchdog: object


def make_watchdog_handlers(ctx: WatchdogHandlerContext) -> WatchdogHandlers:
    @authed(ctx)
    async def handle_v1_watchdog(request: web.Request) -> web.Response:
        """GET /v1/watchdog — Watchdog status and configuration.
        POST /v1/watchdog — Update watchdog settings.
        """

        if request.method == "POST":
            try:
                data = await request.json()
                if "memory_limit_mb" in data:
                    WATCHDOG_STATE["memory_limit_mb"] = int(data["memory_limit_mb"])
                if "cpu_limit_percent" in data:
                    WATCHDOG_STATE["cpu_limit_percent"] = float(data["cpu_limit_percent"])
                if "check_interval_s" in data:
                    WATCHDOG_STATE["check_interval_s"] = max(10, int(data["check_interval_s"]))
                if "auto_restart" in data:
                    WATCHDOG_STATE["auto_restart"] = bool(data["auto_restart"])
                ctx.log_info("[Watchdog] Config updated: %s", data)
            except Exception as e:
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)

        return ctx.cors_json_response({
            "ok": True,
            "memory_mb": WATCHDOG_STATE["memory_mb"],
            "cpu_percent": WATCHDOG_STATE["cpu_percent"],
            "memory_limit_mb": WATCHDOG_STATE["memory_limit_mb"],
            "cpu_limit_percent": WATCHDOG_STATE["cpu_limit_percent"],
            "check_interval_s": WATCHDOG_STATE["check_interval_s"],
            "auto_restart": WATCHDOG_STATE["auto_restart"],
            "last_check": WATCHDOG_STATE["last_check"],
            "restart_count": WATCHDOG_STATE["restart_count"],
            "recent_alerts": WATCHDOG_STATE["alerts"][-10:],
            "uptime_seconds": round(ctx.now() - ctx.metrics["start_time"], 1),
        })

    return WatchdogHandlers(watchdog=handle_v1_watchdog)

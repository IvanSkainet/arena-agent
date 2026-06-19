"""Simple system/version/status/config handlers."""
from __future__ import annotations

import asyncio
import platform
import socket
import sys
from dataclasses import dataclass

from aiohttp import web
from arena.app_keys import APP_CFG

from arena.handler_context import SystemHandlerContext


@dataclass(frozen=True)
class SystemHandlers:
    version: object
    info: object
    status: object
    config: object
    doctor: object
    sysinfo: object
    beep: object


def make_system_handlers(ctx: SystemHandlerContext) -> SystemHandlers:
    async def handle_v1_version(request: web.Request) -> web.Response:
        try:
            ctx.record_request()
            return ctx.cors_json_response({
                "ok": True,
                "version": ctx.version,
                "service": "arena-unified-bridge",
                "python": sys.version.split()[0],
                "platform": ctx.clean_platform_name(),
            })
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_info(request: web.Request) -> web.Response:
        try:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            return ctx.cors_json_response(ctx.common_status(request.app[APP_CFG]))
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_status(request: web.Request) -> web.Response:
        try:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            return ctx.cors_json_response(ctx.common_status(request.app[APP_CFG]))
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_config(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        cfg = request.app[APP_CFG]
        return ctx.cors_json_response({
            "ok": True,
            "service": "arena-unified-bridge",
            "version": ctx.version,
            "host": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "config": {
                "root": str(cfg.get("root", "")),
                "port": cfg.get("port", 8765),
                "profile": cfg.get("profile", "owner-shell"),
                "audit_log": str(cfg.get("audit", "")),
                "max_concurrent": cfg.get("max_concurrent", 3),
                "token_length": len(cfg.get("token", "")) if cfg.get("token") else 0,
                "token_preview": (cfg.get("token", "")[:4] + "..." + cfg.get("token", "")[-4:])
                                 if cfg.get("token") and len(cfg["token"]) > 8 else "***",
            },
            "endpoints_total": len([r for r in request.app.router.routes()]),
        })


    async def handle_v1_doctor(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.doctor_sync, request.app[APP_CFG]["token"])
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_sysinfo(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.sysinfo_sync, request.app[APP_CFG]["root"])
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_beep(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            data = await request.json()
        except Exception:
            data = {}
        beep_type = data.get("type", "success")
        presets = {"success": (800, 300), "warning": (600, 500), "error": (400, 700), "attention": (1000, 200)}
        freq, dur = presets.get(beep_type, (800, 300))
        try:
            freq = int(data.get("frequency", freq))
            dur = int(data.get("duration", dur))
        except Exception:
            freq, dur = presets.get(beep_type, (800, 300))
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.play_beep_sync, beep_type, freq, dur)
        return ctx.cors_json_response(result)
    return SystemHandlers(
        version=handle_v1_version,
        info=handle_v1_info,
        status=handle_v1_status,
        config=handle_v1_config,
        doctor=handle_v1_doctor,
        sysinfo=handle_v1_sysinfo,
        beep=handle_v1_beep,
    )

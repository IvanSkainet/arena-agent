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
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class SystemHandlers:
    version: object
    info: object
    status: object
    config: object
    doctor: object
    sysinfo: object
    beep: object
    notify: object
    mcp_servers: object


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

    @authed(ctx)
    async def handle_v1_config(request: web.Request) -> web.Response:
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


    @authed(ctx)
    async def handle_v1_doctor(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.doctor_sync, request.app[APP_CFG]["token"])
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_sysinfo(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.sysinfo_sync, request.app[APP_CFG]["root"])
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_beep(request: web.Request) -> web.Response:
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
    @authed(ctx)
    async def handle_v1_notify(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            data = {}
        title = str(data.get("title", "Arena Bridge"))
        message = str(data.get("message", ""))
        sound = bool(data.get("sound", True))
        loop = asyncio.get_running_loop()
        res_v = await loop.run_in_executor(ctx.executor, ctx.send_notification_sync, title, message)
        if sound:
            await loop.run_in_executor(ctx.executor, ctx.play_beep_sync, "success", 800, 300)
        return ctx.cors_json_response(res_v)

    @authed(ctx)
    async def handle_v1_mcp_servers(request: web.Request) -> web.Response:
        """GET /v1/mcp/servers — registered external MCP servers + status.

        Powers the Dashboard MCP tab (v4.95.0). Lists every server in
        mcp/mcp.json with its running state and, when running, its tool
        names (best-effort)."""
        from arena.mcp_client import get_manager

        def _gather() -> dict:
            mgr = get_manager()
            servers = mgr.servers()
            out = []
            for name, cfg in sorted(servers.items()):
                st = mgr.status(name)
                entry = {
                    "name": name,
                    "command": cfg.get("command", ""),
                    "args": cfg.get("args", []),
                    "running": st["running"],
                    "tools": [],
                }
                if st["running"]:
                    try:
                        entry["tools"] = [t.get("name", "") for t in mgr.list_tools(name)]
                    except Exception:
                        entry["tools"] = []
                out.append(entry)
            # v4.96.0: agent-authored custom tools (self-extending
            # environment) are part of the same MCP surface, so the cockpit
            # shows them next to the external servers.
            from arena.mcp import custom_tools as _ct
            ctools = []
            for spec in _ct.list_tools():
                schema = spec.get("inputSchema") or {}
                ctools.append({
                    "name": spec.get("name", ""),
                    "description": spec.get("description", ""),
                    "risk": spec.get("risk", "medium"),
                    "wraps": (spec.get("call") or {}).get("tool", ""),
                    "params": list((schema.get("properties") or {}).keys()),
                    "required": schema.get("required", []),
                })
            return {"ok": True, "count": len(out), "servers": out,
                    "custom_tools": ctools}

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, _gather)
        return ctx.cors_json_response(result)

    return SystemHandlers(
        version=handle_v1_version,
        info=handle_v1_info,
        status=handle_v1_status,
        config=handle_v1_config,
        doctor=handle_v1_doctor,
        sysinfo=handle_v1_sysinfo,
        beep=handle_v1_beep,
        notify=handle_v1_notify,
        mcp_servers=handle_v1_mcp_servers,
    )

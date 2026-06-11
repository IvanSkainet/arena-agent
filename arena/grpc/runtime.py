"""Runtime for the gRPC-style secondary JSON interface."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

import aiohttp
from aiohttp import web

GRPC_CONFIG: dict[str, Any] = {
    "enabled": False,
    "port": 50051,
    "running": False,
}
_GRPC_SERVER_TASK: asyncio.Task | None = None

GRPC_METHOD_MAP: dict[str, tuple[str, str]] = {
    "Bridge/Status": ("/v1/status", "GET"),
    "Bridge/Health": ("/health", "GET"),
    "Bridge/Info": ("/v1/info", "GET"),
    "Bridge/Version": ("/v1/version", "GET"),
    "Bridge/Exec": ("/v1/exec", "POST"),
    "Bridge/Skills": ("/v1/skills", "GET"),
    "Bridge/SkillsRun": ("/v1/skills/run", "POST"),
    "Bridge/Memory": ("/v1/memory", "GET"),
    "Bridge/MemorySet": ("/v1/memory", "POST"),
    "Bridge/Tasks": ("/v1/tasks", "GET"),
    "Bridge/Audit": ("/v1/audit", "GET"),
    "Bridge/Recall": ("/v1/recall", "GET"),
    "Bridge/Watchdog": ("/v1/watchdog", "GET"),
    "Bridge/Alerts": ("/v1/alerts", "GET"),
    "Bridge/Users": ("/v1/users", "GET"),
    "Bridge/Batch": ("/v1/batch", "POST"),
    "CDP/Status": ("/v1/browser/cdp/status", "GET"),
    "CDP/Connect": ("/v1/browser/cdp/connect", "POST"),
    "CDP/Disconnect": ("/v1/browser/cdp/disconnect", "POST"),
    "CDP/Navigate": ("/v1/browser/cdp/navigate", "POST"),
    "CDP/Screenshot": ("/v1/browser/cdp/screenshot", "GET"),
    "CDP/Eval": ("/v1/browser/cdp/eval", "POST"),
    "CDP/Tabs": ("/v1/browser/cdp/tabs", "GET"),
}


async def grpc_handler(request: web.Request) -> web.Response:
    """Handle gRPC-style JSON requests on the secondary interface.

    Accepts JSON payloads in the format:
    {"service": "Bridge", "method": "Status", "params": {}}
    Returns JSON responses in the format:
    {"ok": true, "result": {...}}
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    service = data.get("service", "Bridge")
    method = data.get("method", "")
    params = data.get("params", {})

    key = f"{service}/{method}" if method else ""
    route = GRPC_METHOD_MAP.get(key)
    if not route:
        return web.json_response({
            "ok": False,
            "error": f"unknown method: {key}",
            "available": list(GRPC_METHOD_MAP.keys()),
        }, status=404)

    path, http_method = route
    cfg = request.app.get("_bridge_cfg", {})
    port = cfg.get("port", 8765)
    token = cfg.get("token", "")
    url = f"http://127.0.0.1:{port}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            if http_method == "GET":
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    result = await resp.json()
                    return web.json_response({"ok": resp.status < 400, "result": result, "status": resp.status})
            async with session.post(url, headers=headers, json=params,
                                    timeout=aiohttp.ClientTimeout(total=60)) as resp:
                result = await resp.json()
                return web.json_response({"ok": resp.status < 400, "result": result, "status": resp.status})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def grpc_server_loop(
    cfg: dict[str, Any],
    *,
    log_info: Callable[..., None] | None = None,
    log_error: Callable[..., None] | None = None,
) -> None:
    """Run the gRPC-style secondary interface server."""
    port = GRPC_CONFIG["port"]
    app = web.Application(client_max_size=10 * 1024 * 1024)
    app["_bridge_cfg"] = cfg
    app.router.add_post("/call", grpc_handler)
    app.router.add_get("/health", lambda r: web.json_response({"ok": True, "service": "arena-bridge-grpc"}))

    runner: web.AppRunner | None = None
    try:
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
        GRPC_CONFIG["running"] = True
        if log_info:
            log_info("[gRPC] Secondary interface running on http://127.0.0.1:%d/call", port)

        # Keep running until cancelled.
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        if log_info:
            log_info("[gRPC] Secondary interface stopped")
    except Exception as e:
        if log_error:
            log_error("[gRPC] Secondary interface error: %s", e)
    finally:
        GRPC_CONFIG["running"] = False
        if runner is not None:
            try:
                await runner.cleanup()
            except Exception:
                pass


def grpc_server_task() -> asyncio.Task | None:
    """Return current secondary interface task for compatibility/introspection."""
    return _GRPC_SERVER_TASK


def start_grpc_server(
    cfg: dict[str, Any],
    *,
    log_info: Callable[..., None] | None = None,
    log_error: Callable[..., None] | None = None,
) -> asyncio.Task:
    """Start the gRPC-style secondary server task."""
    global _GRPC_SERVER_TASK
    _GRPC_SERVER_TASK = asyncio.create_task(grpc_server_loop(cfg, log_info=log_info, log_error=log_error))
    return _GRPC_SERVER_TASK


async def stop_grpc_server() -> bool:
    """Stop the gRPC-style secondary server. Returns True when a task was stopped."""
    global _GRPC_SERVER_TASK
    if _GRPC_SERVER_TASK and not _GRPC_SERVER_TASK.done():
        _GRPC_SERVER_TASK.cancel()
        try:
            await _GRPC_SERVER_TASK
        except asyncio.CancelledError:
            pass
        _GRPC_SERVER_TASK = None
        GRPC_CONFIG["running"] = False
        return True
    _GRPC_SERVER_TASK = None
    GRPC_CONFIG["running"] = False
    return False

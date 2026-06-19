"""Handlers for managing the gRPC-style secondary interface."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web
from arena.app_keys import APP_CFG

from arena.grpc.runtime import GRPC_CONFIG
from arena.handler_context import GrpcHandlerContext


@dataclass(frozen=True)
class GrpcHandlers:
    grpc: object


def make_grpc_handlers(ctx: GrpcHandlerContext) -> GrpcHandlers:
    async def handle_v1_grpc(request: web.Request) -> web.Response:
        """GET /v1/grpc — gRPC-style interface status.
        POST /v1/grpc — Configure/start/stop the gRPC interface.
        """
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        if request.method == "POST":
            try:
                data = await request.json()
                action = data.get("action", "")

                if action == "start":
                    task = ctx.server_task()
                    if task and not task.done():
                        return ctx.cors_json_response({"ok": False, "error": "already running"}, status=409)
                    GRPC_CONFIG["enabled"] = True
                    if "port" in data:
                        GRPC_CONFIG["port"] = int(data["port"])
                    cfg = request.app[APP_CFG]
                    ctx.start_server(cfg)
                    return ctx.cors_json_response({
                        "ok": True,
                        "message": "gRPC interface starting",
                        "port": GRPC_CONFIG["port"],
                    })

                if action == "stop":
                    stopped = await ctx.stop_server()
                    if stopped:
                        GRPC_CONFIG["enabled"] = False
                        return ctx.cors_json_response({"ok": True, "message": "gRPC interface stopping"})
                    return ctx.cors_json_response({"ok": False, "error": "not running"}, status=404)

                return ctx.cors_json_response({"ok": False, "error": "action must be 'start' or 'stop'"}, status=400)
            except Exception as e:
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)

        return ctx.cors_json_response({
            "ok": True,
            "grpc": {
                "enabled": GRPC_CONFIG["enabled"],
                "port": GRPC_CONFIG["port"],
                "running": GRPC_CONFIG["running"],
                "endpoint": f"http://127.0.0.1:{GRPC_CONFIG['port']}/call",
            }
        })

    return GrpcHandlers(grpc=handle_v1_grpc)

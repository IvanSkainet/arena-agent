"""GET /v1/self -- what this bridge is, can do, and is currently blocked by.

One endpoint, deliberately unauthenticated-shaped like the rest of the
admin surface (it still requires the token). An agent calls it once at
the start of a session and needs nothing else to orient itself.
"""
from __future__ import annotations

from aiohttp import web

from arena import self_description as _sd
from arena.app_keys import APP_CFG
from arena.handler_helpers import authed


def make_self_handlers(ctx):
    @authed(ctx)
    async def handle_self(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]

        tools: list = []
        try:
            from arena.mcp.tool_registry import MCP_TOOLS
            tools = list(MCP_TOOLS)
            from arena.mcp.custom_tools import list_tools as _custom
            tools += list(_custom() or [])
        except Exception:
            # A broken tool import must not take the orientation
            # endpoint down -- an agent with a partial map is far better
            # off than one with a 500.
            pass

        host: dict = {}
        try:
            from arena import hostplatform
            host = hostplatform.describe()
        except Exception:
            pass

        yolo = False
        try:
            from arena.autonomy.yolo import is_yolo
            yolo = bool(is_yolo())
        except Exception:
            pass

        # No bare `except Exception` around this import. That is exactly
        # how the previous version hid a NameError for `control_status`,
        # a function that never existed, and reported "not halted" on a
        # halted bridge. A missing symbol here must break loudly in
        # tests, not degrade quietly in production.
        from arena.control import is_halted
        halted = is_halted()

        posture: dict = {}
        try:
            from arena.autonomy.posture import load_posture
            posture = load_posture() or {}
        except Exception:
            pass

        from arena.constants import VERSION
        return ctx.cors_json_response(_sd.describe(
            tools=tools, host=host,
            profile=str(cfg.get("profile", "cautious")),
            yolo=yolo, halted=halted, posture=posture, version=VERSION))

    return {"self": handle_self}

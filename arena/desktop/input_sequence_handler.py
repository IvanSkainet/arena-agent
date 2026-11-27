"""POST /v1/desktop/sequence: run a timed input sequence on the host (#616)."""
from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from arena.desktop.input_sequence import InputDriver, SequenceError, plan_sequence, run_sequence
from arena.handler_context import DesktopHandlerContext
from arena.handler_helpers import controlled, json_object_body

#: How a sequence that stopped early is reported; anything else it returns is a 200.
_STOP_STATUS = {
    "input_guard_failed": 409,
    "control_paused": 403,
    "control_revoked": 403,
    "agent_halted": 403,
    "input_failed": 500,
}
_NOT_HERE = (
    "input sequences are implemented for the native Windows input backend only; "
    "this desktop has no driver for them yet"
)


def sequence_driver(env: dict[str, Any]) -> InputDriver | None:
    """The driver for this desktop, or None where sequences are not implemented."""
    if not env.get("has_win32_input"):
        return None
    from arena.desktop.backends import windows_input  # pragma: no cover -- Windows only

    return windows_input.system_driver()  # pragma: no cover -- Windows only


def _required_title(body: dict[str, Any]) -> str:
    title = body.get("require_active_title")
    return title.strip() if isinstance(title, str) else ""


def make_desktop_sequence_handler(ctx: DesktopHandlerContext):
    def _refuse(payload: dict[str, Any], status: int) -> web.Response:
        ctx.record_request(is_error=True, count_request=False)
        return ctx.cors_json_response({"ok": False, **payload}, status=status)

    @controlled(ctx)
    async def handle_v1_desktop_sequence(request: web.Request) -> web.Response:
        body = await json_object_body(request)
        title = _required_title(body)
        if not title:
            return _refuse({"error": "'require_active_title' is required: name the window this input is for"}, 400)
        driver = sequence_driver(ctx.detect_desktop_env())
        if driver is None:
            return _refuse({"error": _NOT_HERE}, 501)
        try:
            steps = plan_sequence(body.get("steps"), driver)
        except SequenceError as exc:
            return _refuse({"error": str(exc), "step": exc.index}, 400)
        ctx.control_record_agent_action()
        result = await asyncio.get_running_loop().run_in_executor(
            None, lambda: run_sequence(steps, driver, required_title=title, should_stop=ctx.control_check))
        status = _STOP_STATUS.get(str(result.get("error")), 200)
        if status != 200:
            ctx.record_request(is_error=True, count_request=False)
        return ctx.cors_json_response(result, status=status)

    return handle_v1_desktop_sequence

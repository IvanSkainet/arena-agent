"""aiohttp handlers for /v1/mobile/*.

Handlers are thin — parse the request, dispatch to the right module,
respond. All heavy lifting lives in arena.mobile.{devices,screenshot,
input,shell,packages}.
"""
from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from arena.mobile import devices as _devices
from arena.mobile import gestures as _gestures
from arena.mobile import input as _input
from arena.mobile import packages as _packages
from arena.mobile import screenshot as _screenshot
from arena.mobile import shell as _shell


@dataclass(frozen=True)
class MobileHandlers:
    list_devices: object
    device_info: object
    screenshot: object
    tap: object
    swipe: object
    type_text: object
    key_event: object
    shell: object
    packages: object
    gesture: object


def make_mobile_handlers(ctx) -> MobileHandlers:
    """Create every /v1/mobile/* handler bound to `ctx`.

    `ctx` is expected to provide the same shape as other Arena admin
    contexts: require_auth, record_request, cors_json_response, executor,
    audit. This mirrors AdminHandlerContext without adding new required
    fields, so wiring stays minimal.
    """

    async def _run(fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(ctx.executor, functools.partial(fn, *args, **kwargs))

    def _cors(payload, status=200):
        return ctx.cors_json_response(payload, status=status)

    async def handle_list_devices(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            return _cors(await _run(_devices.list_devices))
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_device_info(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        if not serial:
            return _cors({"ok": False, "error": "serial required"}, status=400)
        try:
            return _cors(await _run(_devices.device_info, serial))
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_screenshot(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        if not serial:
            return _cors({"ok": False, "error": "serial required"}, status=400)

        # Query params: max_width, quality, format (raw|json)
        try:
            max_width = int(request.query.get("max_width")) if request.query.get("max_width") else None
            quality = int(request.query.get("quality", "85"))
        except ValueError as e:
            return _cors({"ok": False, "error": f"invalid query param: {e}"}, status=400)
        fmt = request.query.get("format", "png").lower()
        wire = request.query.get("wire", "raw").lower()  # "raw" (binary) | "json" (b64)

        try:
            result = await _run(
                _screenshot.capture,
                serial,
                max_width=max_width,
                quality=quality,
                format=fmt,
            )
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

        if not result.get("ok"):
            return _cors(result, status=502)

        if wire == "json":
            import base64
            b = result.pop("bytes")
            result["base64"] = base64.b64encode(b).decode("ascii")
            return _cors(result)
        return web.Response(
            body=result["bytes"],
            content_type=result["mime"],
            headers={
                "X-Arena-Mobile-Width": str(result["width"]),
                "X-Arena-Mobile-Height": str(result["height"]),
                "X-Arena-Mobile-Downscaled": "1" if result.get("downscaled") else "0",
            },
        )

    async def _read_json(request: web.Request) -> dict:
        try:
            return await request.json() or {}
        except Exception:
            return {}

    async def handle_tap(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        x = body.get("x")
        y = body.get("y")
        try:
            res = await _run(_input.tap, serial, x, y)
            ctx.audit({"type": "mobile.tap", "serial": serial, "ok": res.get("ok")})
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_swipe(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        try:
            res = await _run(
                _input.swipe,
                serial,
                body.get("x1"), body.get("y1"),
                body.get("x2"), body.get("y2"),
                body.get("duration_ms", 300),
            )
            ctx.audit({"type": "mobile.swipe", "serial": serial, "ok": res.get("ok")})
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_type(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        text = body.get("text", "")
        try:
            res = await _run(_input.type_text, serial, text)
            ctx.audit({"type": "mobile.type", "serial": serial, "chars": len(text), "ok": res.get("ok")})
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_key(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        key = body.get("key", "") or request.query.get("key", "")
        try:
            res = await _run(_input.key, serial, key)
            ctx.audit({"type": "mobile.key", "serial": serial, "key": key, "ok": res.get("ok")})
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_shell(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        cmd = body.get("command", "")
        try:
            res = await _run(_shell.restricted_shell, serial, cmd)
            ctx.audit({"type": "mobile.shell", "serial": serial, "cmd_head": cmd.split()[:1], "ok": res.get("ok")})
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_gesture(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        gesture = body.get("gesture", "") or request.query.get("gesture", "")
        try:
            res = await _run(_gestures.perform, serial, gesture)
            ctx.audit({"type": "mobile.gesture", "serial": serial,
                       "gesture": gesture, "ok": res.get("ok")})
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_packages(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        filter_text = request.query.get("filter")
        include_system = request.query.get("include_system", "1") not in ("0", "false", "False")
        include_disabled = request.query.get("include_disabled", "0") in ("1", "true", "True")
        try:
            res = await _run(
                _packages.list_packages,
                serial,
                filter_text=filter_text,
                include_system=include_system,
                include_disabled=include_disabled,
            )
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    return MobileHandlers(
        list_devices=handle_list_devices,
        device_info=handle_device_info,
        screenshot=handle_screenshot,
        tap=handle_tap,
        swipe=handle_swipe,
        type_text=handle_type,
        key_event=handle_key,
        shell=handle_shell,
        packages=handle_packages,
        gesture=handle_gesture,
    )

"""aiohttp handlers for the camera / media corner of /v1/mobile/*.

Split out of `handlers.py` in v3.84.1 to keep the main handlers module
under its 600-line runtime cap. Everything here uses `arena.mobile.camera`.
"""
from __future__ import annotations

from aiohttp import web

from arena.mobile import camera as _camera


def make_media_handlers(ctx, *, run, read_json, cors):
    """Return the 5 camera/media handler coroutines."""

    async def handle_camera_launch(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await read_json(request)
        intent = body.get("intent", "still")
        package = body.get("package")
        try:
            res = await run(_camera.launch, serial,
                            intent=intent, package=package)
            ctx.audit({"type": "mobile.camera.launch",
                       "serial": serial, "intent": intent,
                       "package": package, "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return cors({"ok": False, "error": str(e)}, status=500)

    async def handle_camera_shutter(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await read_json(request)
        try:
            res = await run(_camera.shutter, serial,
                            shutter_x=body.get("shutter_x"),
                            shutter_y=body.get("shutter_y"))
            ctx.audit({"type": "mobile.camera.shutter",
                       "serial": serial, "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return cors({"ok": False, "error": str(e)}, status=500)

    async def handle_camera_photos(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        try:
            limit = int(request.query.get("limit", "10"))
        except ValueError:
            limit = 10
        try:
            res = await run(_camera.list_photos, serial, limit=limit)
            return cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return cors({"ok": False, "error": str(e)}, status=500)

    async def handle_camera_pull(request: web.Request) -> web.Response:
        """Pull a specific photo off the phone. Body: {path, max_size?,
        format?, quality?}."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await read_json(request)
        path = body.get("path", "")
        try:
            res = await run(
                _camera.pull_photo, serial, path,
                max_size=body.get("max_size"),
                format=body.get("format", "jpeg"),
                quality=int(body.get("quality", 85)),
            )
            ctx.audit({"type": "mobile.camera.pull",
                       "serial": serial, "path": path,
                       "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return cors({"ok": False, "error": str(e)}, status=500)

    async def handle_camera_capture(request: web.Request) -> web.Response:
        """One-shot: launch → shutter → poll DCIM → pull the new file.
        Body accepts every arg of `camera.capture_and_pull`."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await read_json(request)
        try:
            res = await run(
                _camera.capture_and_pull, serial,
                shutter_x=body.get("shutter_x"),
                shutter_y=body.get("shutter_y"),
                wait_before_shutter_ms=int(body.get("wait_before_shutter_ms", 1500)),
                wait_for_file_ms=int(body.get("wait_for_file_ms", 5000)),
                max_size=body.get("max_size", 1024),
                format=body.get("format", "jpeg"),
                quality=int(body.get("quality", 85)),
                package=body.get("package"),
            )
            ctx.audit({"type": "mobile.camera.capture",
                       "serial": serial, "ok": res.get("ok"),
                       "duration_ms": res.get("total_duration_ms")})
            return cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return cors({"ok": False, "error": str(e)}, status=500)

    return {
        "camera_launch":  handle_camera_launch,
        "camera_shutter": handle_camera_shutter,
        "camera_photos":  handle_camera_photos,
        "camera_pull":    handle_camera_pull,
        "camera_capture": handle_camera_capture,
    }

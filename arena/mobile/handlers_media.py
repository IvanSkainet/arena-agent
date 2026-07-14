"""aiohttp handlers for the camera / media corner of /v1/mobile/*.

Split out of `handlers.py` in v3.84.1 to keep the main handlers module
under its 600-line runtime cap. Everything here uses
`arena.mobile.camera` (+ `arena.mobile.camera_controls` since v3.84.4).
"""
from __future__ import annotations

from aiohttp import web

from arena.mobile import camera as _camera
from arena.mobile import camera_controls as _cc


def _serial(request: web.Request) -> str:
    return request.match_info.get("serial", "")


def _guard(ctx, request):
    r = ctx.require_auth(request)
    if r:
        return r
    ctx.record_request()
    return None


def _oops(ctx, cors, exc):
    ctx.record_request(is_error=True, count_request=False)
    return cors({"ok": False, "error": str(exc)}, status=500)


def make_media_handlers(ctx, *, run, read_json, cors):
    """Return the camera/media handler coroutines (v3.84.4: 12 total)."""

    async def handle_camera_launch(request):
        r = _guard(ctx, request)
        if r:
            return r
        serial = _serial(request)
        body = await read_json(request)
        try:
            res = await run(_camera.launch, serial,
                            intent=body.get("intent", "still"),
                            package=body.get("package"))
            ctx.audit({"type": "mobile.camera.launch",
                       "serial": serial, "intent": body.get("intent"),
                       "package": body.get("package"), "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            return _oops(ctx, cors, e)

    async def handle_camera_shutter(request):
        r = _guard(ctx, request)
        if r:
            return r
        serial = _serial(request)
        body = await read_json(request)
        try:
            res = await run(_camera.shutter, serial,
                            shutter_x=body.get("shutter_x"),
                            shutter_y=body.get("shutter_y"))
            ctx.audit({"type": "mobile.camera.shutter",
                       "serial": serial, "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            return _oops(ctx, cors, e)

    async def handle_camera_photos(request):
        r = _guard(ctx, request)
        if r:
            return r
        serial = _serial(request)
        try:
            limit = int(request.query.get("limit", "10"))
        except ValueError:
            limit = 10
        try:
            res = await run(_camera.list_photos, serial, limit=limit)
            return cors(res)
        except Exception as e:
            return _oops(ctx, cors, e)

    async def handle_camera_pull(request):
        r = _guard(ctx, request)
        if r:
            return r
        serial = _serial(request)
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
            return _oops(ctx, cors, e)

    async def handle_camera_capture(request):
        r = _guard(ctx, request)
        if r:
            return r
        serial = _serial(request)
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
            return _oops(ctx, cors, e)

    # ---- v3.84.4 additions ------------------------------------------------

    async def handle_camera_controls(request):
        r = _guard(ctx, request)
        if r:
            return r
        serial = _serial(request)
        try:
            res = await run(_cc.list_controls, serial)
            return cors(res)
        except Exception as e:
            return _oops(ctx, cors, e)

    async def handle_camera_mode(request):
        r = _guard(ctx, request)
        if r:
            return r
        serial = _serial(request)
        body = await read_json(request)
        mode = body.get("mode", "")
        try:
            res = await run(_cc.switch_mode, serial, mode)
            ctx.audit({"type": "mobile.camera.mode", "serial": serial,
                       "mode": mode, "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            return _oops(ctx, cors, e)

    async def handle_camera_lens(request):
        r = _guard(ctx, request)
        if r:
            return r
        serial = _serial(request)
        body = await read_json(request)
        target = body.get("target", "toggle")
        try:
            res = await run(_cc.switch_lens, serial, target)
            ctx.audit({"type": "mobile.camera.lens", "serial": serial,
                       "target": target, "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            return _oops(ctx, cors, e)

    async def handle_camera_zoom(request):
        r = _guard(ctx, request)
        if r:
            return r
        serial = _serial(request)
        body = await read_json(request)
        level = body.get("level")
        try:
            res = await run(_cc.set_zoom, serial, level)
            ctx.audit({"type": "mobile.camera.zoom", "serial": serial,
                       "level": level, "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            return _oops(ctx, cors, e)

    async def handle_camera_flash(request):
        r = _guard(ctx, request)
        if r:
            return r
        serial = _serial(request)
        body = await read_json(request)
        mode = body.get("mode", "")
        try:
            res = await run(_cc.set_flash, serial, mode)
            ctx.audit({"type": "mobile.camera.flash", "serial": serial,
                       "mode": mode, "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            return _oops(ctx, cors, e)

    async def handle_camera_record_start(request):
        r = _guard(ctx, request)
        if r:
            return r
        serial = _serial(request)
        body = await read_json(request)
        try:
            res = await run(
                _cc.record_start, serial,
                wait_after_mode_ms=int(body.get("wait_after_mode_ms", 900)),
                wait_after_shutter_ms=int(body.get("wait_after_shutter_ms", 500)),
            )
            ctx.audit({"type": "mobile.camera.record_start",
                       "serial": serial, "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            return _oops(ctx, cors, e)

    async def handle_camera_record_stop(request):
        r = _guard(ctx, request)
        if r:
            return r
        serial = _serial(request)
        body = await read_json(request)
        try:
            res = await run(
                _cc.record_stop, serial,
                wait_for_file_ms=int(body.get("wait_for_file_ms", 12000)),
                pull=bool(body.get("pull", False)),
                max_size=body.get("max_size"),
                format=body.get("format", "jpeg"),
                quality=int(body.get("quality", 85)),
            )
            ctx.audit({"type": "mobile.camera.record_stop",
                       "serial": serial, "ok": res.get("ok"),
                       "video_path": res.get("video_path")})
            return cors(res)
        except Exception as e:
            return _oops(ctx, cors, e)

    return {
        "camera_launch":       handle_camera_launch,
        "camera_shutter":      handle_camera_shutter,
        "camera_photos":       handle_camera_photos,
        "camera_pull":         handle_camera_pull,
        "camera_capture":      handle_camera_capture,
        "camera_controls":     handle_camera_controls,
        "camera_mode":         handle_camera_mode,
        "camera_lens":         handle_camera_lens,
        "camera_zoom":         handle_camera_zoom,
        "camera_flash":        handle_camera_flash,
        "camera_record_start": handle_camera_record_start,
        "camera_record_stop":  handle_camera_record_stop,
    }

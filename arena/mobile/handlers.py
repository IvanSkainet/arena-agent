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

from arena.mobile import batch as _batch
from arena.mobile import devices as _devices
from arena.mobile import gestures as _gestures
from arena.mobile import helpers as _helpers
from arena.mobile import input as _input
from arena.mobile import packages as _packages
from arena.mobile import screenshot as _screenshot
from arena.mobile import sensors as _sensors
from arena.mobile import shell as _shell
from arena.mobile import ui as _ui
# apk_install and wireless are used indirectly via handlers_devops.


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
    ui_dump: object
    tap_by: object
    helpers_status: object
    helpers_install: object
    ime_status: object
    ime_set: object
    ime_reset: object
    paste: object
    sensors: object
    scroll: object
    key_combo: object
    # v3.83.5 additions.
    pair: object
    connect: object
    disconnect: object
    apk_prepare: object
    apk_install: object
    # v3.84.0 additions.
    batch: object
    # v3.84.1: camera & media
    camera_launch: object
    camera_shutter: object
    camera_photos: object
    camera_pull: object
    camera_capture: object


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

        # Query params: max_width (legacy), max_size (long side, preferred),
        # quality, format, wire (raw|json), force_png_source (v3.83.5:
        # skip the fast raw path so testers can compare paths side-by-side
        # straight from the browser).
        try:
            max_width = int(request.query.get("max_width")) if request.query.get("max_width") else None
            max_size = int(request.query.get("max_size")) if request.query.get("max_size") else None
            quality = int(request.query.get("quality", "85"))
        except ValueError as e:
            return _cors({"ok": False, "error": f"invalid query param: {e}"}, status=400)
        fmt = request.query.get("format", "png").lower()
        wire = request.query.get("wire", "raw").lower()  # "raw" (binary) | "json" (b64)
        force_png = request.query.get("force_png_source", "0") in ("1", "true", "True")

        try:
            result = await _run(
                _screenshot.capture,
                serial,
                max_width=max_width,
                max_size=max_size,
                quality=quality,
                format=fmt,
                force_png_source=force_png,
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
                # Native device pixels in the *current* rotation. These
                # are what `input tap` expects, so the frontend uses
                # them (not /info physical size) to unscale clicks.
                "X-Arena-Mobile-Source-Width": str(result.get("source_width") or result["width"]),
                "X-Arena-Mobile-Source-Height": str(result.get("source_height") or result["height"]),
                "X-Arena-Mobile-Downscaled": "1" if result.get("downscaled") else "0",
                # v3.83.4: expose latency breakdown so the Dashboard
                # meta line can show what actually dominates the frame
                # (capture on device vs encode on bridge vs network
                # round-trip).
                "X-Arena-Mobile-Capture-Mode": str(result.get("capture_mode") or ""),
                "X-Arena-Mobile-Capture-Ms": str(result.get("capture_ms") or 0),
                "X-Arena-Mobile-Encode-Ms": str(result.get("encode_ms") or 0),
                "X-Arena-Mobile-Secure-Frame": "1" if result.get("secure_frame") else "0",
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

    async def handle_ui_dump(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        # Query params: interactive_only (default 1), include_full_tree
        # (default 0), max_nodes (default 500).
        interactive = request.query.get("interactive_only", "1") not in ("0", "false", "False")
        include_full = request.query.get("include_full_tree", "0") in ("1", "true", "True")
        try:
            max_nodes = int(request.query.get("max_nodes", "500"))
        except ValueError:
            max_nodes = 500
        try:
            res = await _run(
                _ui.dump_ui, serial,
                interactive_only=interactive,
                include_full_tree=include_full,
                max_nodes=max_nodes,
            )
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_tap_by(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        selector = {
            "id": body.get("id"),
            "text": body.get("text"),
            "desc": body.get("desc"),
            "class_name": body.get("class_name") or body.get("class"),
            "package": body.get("package"),
            "index": body.get("index"),
            "match": body.get("match", "exact"),
        }
        try:
            res = await _run(_ui.tap_by, serial, **selector)
            ctx.audit({
                "type": "mobile.tap_by",
                "serial": serial,
                "selector": {k: v for k, v in selector.items() if v not in (None, "")},
                "ok": res.get("ok"),
            })
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    # ---- helper-APK install + IME control + unicode paste -----------

    async def handle_helpers_status(request: web.Request) -> web.Response:
        """Report on the bundled ADBKeyboard APK (no device needed).

        Advertises the expected consent token so the Dashboard doesn't
        have to guess it. Never touches the device — reads the on-disk
        bundle only. This is the endpoint the install-consent UI polls
        before showing its confirm button.
        """
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            info = await _run(_helpers.bundled_apk_status)
            # Include the required consent token so the Dashboard can
            # show it exactly instead of reconstructing on the client.
            if info.get("ok") and info.get("sha256"):
                info["required_consent"] = _helpers._consent_token(info["sha256"])
            return _cors(info)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_helpers_install(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        consent = body.get("consent")
        try:
            res = await _run(_helpers.install_adbkeyboard, serial, consent=consent)
            ctx.audit({
                "type": "mobile.helpers.install",
                "serial": serial,
                "package": _helpers.ADBKEYBOARD_PACKAGE,
                "ok": res.get("ok"),
            })
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_ime_status(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        try:
            return _cors(await _run(_helpers.ime_status, serial))
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_ime_set(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        try:
            res = await _run(_helpers.ime_set_adbkeyboard, serial)
            ctx.audit({
                "type": "mobile.helpers.ime_set",
                "serial": serial,
                "target": _helpers.ADBKEYBOARD_SERVICE,
                "ok": res.get("ok"),
            })
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_ime_reset(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        target = body.get("target")
        try:
            res = await _run(_helpers.ime_reset, serial, target=target)
            ctx.audit({
                "type": "mobile.helpers.ime_reset",
                "serial": serial,
                "target": target,
                "ok": res.get("ok"),
            })
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_paste(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        text = body.get("text", "")
        try:
            res = await _run(_helpers.paste_text, serial, text)
            ctx.audit({
                "type": "mobile.helpers.paste",
                "serial": serial,
                "chars": len(text),
                "ok": res.get("ok"),
            })
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

    async def handle_sensors(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        include_recent = request.query.get("include_recent_events", "1") not in ("0", "false", "False")
        try:
            events_per = int(request.query.get("events_per_sensor", "1"))
        except ValueError:
            events_per = 1
        try:
            res = await _run(
                _sensors.list_sensors, serial,
                include_recent_events=include_recent,
                events_per_sensor=events_per,
            )
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_scroll(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        try:
            res = await _run(
                _input.scroll, serial,
                body.get("x"), body.get("y"),
                vscroll=body.get("vscroll", 0), hscroll=body.get("hscroll", 0),
            )
            ctx.audit({"type": "mobile.scroll", "serial": serial,
                       "vscroll": body.get("vscroll"), "hscroll": body.get("hscroll"),
                       "ok": res.get("ok")})
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_key_combo(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        keys = body.get("keys") or []
        try:
            res = await _run(_input.key_combo, serial, keys)
            ctx.audit({"type": "mobile.key_combo", "serial": serial,
                       "keys": keys, "ok": res.get("ok")})
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_batch(request: web.Request) -> web.Response:
        """v3.84.0: N steps in one HTTP round-trip. See arena.mobile.batch."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await _read_json(request)
        steps = body.get("steps") or []
        stop_on_error = body.get("stop_on_error", True)
        try:
            res = await _run(_batch.run_batch, serial, steps,
                             stop_on_error=bool(stop_on_error))
            ctx.audit({"type": "mobile.batch", "serial": serial,
                       "step_count": res.get("step_count"),
                       "executed": res.get("executed"),
                       "ok": res.get("ok")})
            return _cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    # Devops (v3.83.5: pair/connect/disconnect/apk_*) + media
    # (v3.84.1: camera_*) live in sibling handlers modules so this
    # file stays under the 600-line runtime cap.
    from arena.mobile.handlers_devops import make_devops_handlers
    from arena.mobile.handlers_media import make_media_handlers
    _devops = make_devops_handlers(ctx, run=_run, read_json=_read_json, cors=_cors)
    _media = make_media_handlers(ctx, run=_run, read_json=_read_json, cors=_cors)


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
        ui_dump=handle_ui_dump,
        tap_by=handle_tap_by,
        helpers_status=handle_helpers_status,
        helpers_install=handle_helpers_install,
        ime_status=handle_ime_status,
        ime_set=handle_ime_set,
        ime_reset=handle_ime_reset,
        paste=handle_paste,
        sensors=handle_sensors,
        scroll=handle_scroll,
        key_combo=handle_key_combo,
        **{k: _devops[k] for k in (
            "pair", "connect", "disconnect",
            "apk_prepare", "apk_install")},
        batch=handle_batch,
        **{k: _media[k] for k in (
            "camera_launch", "camera_shutter",
            "camera_photos", "camera_pull", "camera_capture")},
    )

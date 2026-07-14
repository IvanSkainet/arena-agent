"""aiohttp handlers for the "devops" corner of /v1/mobile/*.

Split out of `handlers.py` in v3.83.5 to keep both files under the
600-line runtime module cap. Everything here operates on the adb
daemon (wireless pair/connect/disconnect) or a file on the bridge
(APK prepare/install) rather than mutating device state directly.
"""
from __future__ import annotations

from aiohttp import web

from arena.mobile import apk_install as _apk_install
from arena.mobile import wireless as _wireless


def make_devops_handlers(ctx, *, run, read_json, cors):
    """Return a dict of 5 devops handler coroutines.

    Called from arena.mobile.handlers.make_mobile_handlers; the shared
    plumbing helpers (`run`, `read_json`, `cors`) live over there so
    this module doesn't reimplement any bridge internals.
    """

    async def handle_pair(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        body = await read_json(request)
        host = body.get("host", "")
        port = body.get("port")
        code = body.get("code", "")
        try:
            res = await run(_wireless.pair, host, port, code)
            # DO NOT audit the 6-digit code — it's short-lived and
            # sensitive. Log host:port + outcome only.
            ctx.audit({"type": "mobile.pair",
                       "host": host, "port": port, "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return cors({"ok": False, "error": str(e)}, status=500)

    async def handle_connect(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        body = await read_json(request)
        host = body.get("host", "")
        port = body.get("port", 5555)
        try:
            res = await run(_wireless.connect, host, port)
            ctx.audit({"type": "mobile.connect",
                       "host": host, "port": port, "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return cors({"ok": False, "error": str(e)}, status=500)

    async def handle_disconnect(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        body = await read_json(request)
        host = body.get("host")
        port = body.get("port")
        try:
            res = await run(_wireless.disconnect, host, port)
            ctx.audit({"type": "mobile.disconnect",
                       "host": host, "port": port, "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return cors({"ok": False, "error": str(e)}, status=500)

    async def handle_apk_prepare(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        # Accept either JSON body {apk_path: ...} or query param for
        # convenience during ad-hoc testing.
        body = await read_json(request)
        apk_path = body.get("apk_path") or request.query.get("apk_path", "")
        try:
            res = await run(_apk_install.prepare, apk_path)
            return cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return cors({"ok": False, "error": str(e)}, status=500)

    async def handle_apk_install(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        serial = request.match_info.get("serial", "")
        body = await read_json(request)
        apk_path = body.get("apk_path", "")
        consent = body.get("consent")
        try:
            res = await run(_apk_install.install, serial, apk_path,
                            consent=consent)
            # Audit records the SHA (present in the successful response
            # or in the error's `apk_sha256` field) but not the file
            # path — the SHA is what identifies the artefact.
            ctx.audit({
                "type": "mobile.apk_install",
                "serial": serial,
                "apk_sha256": res.get("sha256") or res.get("apk_sha256"),
                "ok": res.get("ok"),
            })
            return cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return cors({"ok": False, "error": str(e)}, status=500)

    async def handle_apk_upload(request: web.Request) -> web.Response:
        """v3.84.2: accept a raw-body upload → saves under staging dir
        → prepares SHA + consent token. Body is the APK bytes; the
        filename comes from `?filename=` query param (required).
        Cap upload at 500 MB to prevent abuse."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        filename = request.query.get("filename") or ""
        MAX_UPLOAD = 500 * 1024 * 1024
        try:
            data = await request.read()
        except Exception as e:
            return cors({"ok": False, "error": f"read body failed: {e}"}, status=400)
        if len(data) > MAX_UPLOAD:
            return cors({"ok": False,
                         "error": f"upload too large: {len(data)} bytes",
                         "hint": f"limit is {MAX_UPLOAD} bytes"}, status=413)
        try:
            res = await run(_apk_install.save_upload, filename, data)
            ctx.audit({"type": "mobile.apk_upload",
                       "filename": filename,
                       "size_bytes": len(data),
                       "apk_sha256": res.get("sha256"),
                       "ok": res.get("ok")})
            return cors(res)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return cors({"ok": False, "error": str(e)}, status=500)

    return {
        "pair": handle_pair,
        "connect": handle_connect,
        "disconnect": handle_disconnect,
        "apk_prepare": handle_apk_prepare,
        "apk_install": handle_apk_install,
        "apk_upload": handle_apk_upload,
    }

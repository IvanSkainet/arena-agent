"""aiohttp handlers for /v1/mobile/{s}/recording/* (v3.84.2)."""
from __future__ import annotations

from aiohttp import web

from arena.handler_helpers import authed, err_json

from arena.mobile import recording as _rec


def make_recording_handlers(ctx, *, run, read_json, cors):
    @authed(ctx)
    async def handle_record_sync(request: web.Request) -> web.Response:
        serial = request.match_info.get("serial", "")
        body = await read_json(request)
        res = await run(
            _rec.record_sync, serial,
            duration_ms=int(body.get("duration_ms", 5000)),
            size=body.get("size"),
            bit_rate=int(body.get("bit_rate", 4_000_000)),
            include_bytes=bool(body.get("include_bytes", True)),
            keep_on_device=bool(body.get("keep_on_device", False)),
        )
        ctx.audit({"type": "mobile.record_sync", "serial": serial,
                   "duration_ms": body.get("duration_ms"),
                   "ok": res.get("ok"),
                   "size_bytes": res.get("size_bytes")})
        return cors(res)

    @authed(ctx)
    async def handle_record_start(request: web.Request) -> web.Response:
        serial = request.match_info.get("serial", "")
        body = await read_json(request)
        res = await run(
            _rec.start_async, serial,
            duration_ms=int(body.get("duration_ms", 30_000)),
            size=body.get("size"),
            bit_rate=int(body.get("bit_rate", 4_000_000)),
        )
        ctx.audit({"type": "mobile.record_start", "serial": serial,
                   "id": res.get("id"), "ok": res.get("ok")})
        return cors(res)

    @authed(ctx)
    async def handle_record_stop(request: web.Request) -> web.Response:
        rec_id = request.match_info.get("rec_id", "")
        res = await run(_rec.stop_async, rec_id)
        ctx.audit({"type": "mobile.record_stop",
                   "id": rec_id, "ok": res.get("ok")})
        return cors(res)

    @authed(ctx)
    async def handle_record_list(request: web.Request) -> web.Response:
        serial = request.match_info.get("serial") or request.query.get("serial")
        res = await run(_rec.list_recordings, serial)
        return cors(res)

    @authed(ctx)
    async def handle_record_pull(request: web.Request) -> web.Response:
        rec_id = request.match_info.get("rec_id", "")
        include = request.query.get("include_bytes", "1") not in ("0", "false", "False")
        res = await run(_rec.pull_recording, rec_id, include_bytes=include)
        return cors(res)

    @authed(ctx)
    async def handle_record_purge(request: web.Request) -> web.Response:
        serial = request.match_info.get("serial", "")
        try:
            older = int(request.query.get("older_than_seconds", "0"))
        except ValueError:
            older = 0
        res = await run(_rec.purge_recordings, serial,
                        older_than_seconds=older)
        ctx.audit({"type": "mobile.record_purge",
                   "serial": serial, "cleared": len(res.get("cleared_ids") or []),
                   "ok": res.get("ok")})
        return cors(res)

    return {
        "record_sync":  handle_record_sync,
        "record_start": handle_record_start,
        "record_stop":  handle_record_stop,
        "record_list":  handle_record_list,
        "record_pull":  handle_record_pull,
        "record_purge": handle_record_purge,
    }

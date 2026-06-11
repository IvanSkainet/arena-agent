"""Handlers for file upload/download endpoints."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web

from arena.files.sandbox import validate_download_target, validate_upload_target
from arena.handler_context import FileHandlerContext


@dataclass(frozen=True)
class FileHandlers:
    upload: object
    download: object


def make_file_handlers(ctx: FileHandlerContext) -> FileHandlers:
    async def handle_v1_upload(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        qs = parse_qs(request.query_string)
        target = qs.get("path", [""])[0]
        target_path, err, status = validate_upload_target(
            target,
            root=request.app["cfg"]["root"],
            home=ctx.home,
            bridge_py=ctx.bridge_py,
        )
        if err:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": err}, status=status)
        content_type = request.headers.get("Content-Type", "")
        if "multipart" in content_type.lower():
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "multipart/form-data not supported; use --data-binary"}, status=400)
        try:
            body = await request.read()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(body)
            ctx.audit({"type": "file_upload", "path": str(target_path), "bytes": len(body)})
            ctx.record_request()
            return ctx.cors_json_response({"ok": True, "path": str(target_path), "bytes": len(body)})
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Internal error"}, status=500)

    async def handle_v1_download(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        qs = parse_qs(request.query_string)
        target = qs.get("path", [""])[0]
        target_path, err, status = validate_download_target(
            target,
            root=request.app["cfg"]["root"],
            home=ctx.home,
        )
        if err:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": err}, status=status)
        try:
            ctx.audit({"type": "file_download", "path": str(target_path), "bytes": target_path.stat().st_size})
            ctx.record_request()
            return web.FileResponse(target_path, headers={
                "Content-Disposition": f'attachment; filename="{target_path.name}"',
                "Access-Control-Allow-Origin": "*",
            })
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Internal error"}, status=500)

    return FileHandlers(upload=handle_v1_upload, download=handle_v1_download)

"""Handlers for file upload/download endpoints."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web
from arena.app_keys import APP_CFG

from arena.files.sandbox import validate_download_target, validate_edit_target, validate_upload_target
from arena.handler_context import FileHandlerContext


@dataclass(frozen=True)
class FileHandlers:
    upload: object
    download: object
    fs_edit: object
    fs_edit_apply: object
    fs_edit_rollback: object



def _json_error(ctx: FileHandlerContext, message: str, status: int) -> web.Response:
    if status >= 400:
        ctx.record_request(is_error=True, count_request=False)
    return ctx.cors_json_response({"ok": False, "error": message}, status=status)



def make_file_handlers(ctx: FileHandlerContext) -> FileHandlers:
    async def handle_v1_upload(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        qs = parse_qs(request.query_string)
        target = qs.get("path", [""])[0]
        target_path, err, status = validate_upload_target(target, root=request.app[APP_CFG]["root"], home=ctx.home, bridge_py=ctx.bridge_py)
        if err:
            return _json_error(ctx, err, status)
        if "multipart" in request.headers.get("Content-Type", "").lower():
            return _json_error(ctx, "multipart/form-data not supported; use --data-binary", 400)
        try:
            body = await request.read()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(body)
            ctx.audit({"type": "file_upload", "path": str(target_path), "bytes": len(body)})
            ctx.record_request()
            return ctx.cors_json_response({"ok": True, "path": str(target_path), "bytes": len(body)})
        except Exception:
            return _json_error(ctx, "Internal error", 500)

    async def handle_v1_download(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        qs = parse_qs(request.query_string)
        target = qs.get("path", [""])[0]
        target_path, err, status = validate_download_target(target, root=request.app[APP_CFG]["root"], home=ctx.home)
        if err:
            return _json_error(ctx, err, status)
        try:
            ctx.audit({"type": "file_download", "path": str(target_path), "bytes": target_path.stat().st_size})
            ctx.record_request()
            return web.FileResponse(target_path, headers={"Content-Disposition": f'attachment; filename="{target_path.name}"', "Access-Control-Allow-Origin": "*"})
        except Exception:
            return _json_error(ctx, "Internal error", 500)

    async def handle_v1_fs_edit(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        try:
            data = await request.json()
        except Exception:
            return _json_error(ctx, "invalid JSON body", 400)
        target = str(data.get("path", ""))
        old_text = str(data.get("old_text", ""))
        new_text = str(data.get("new_text", ""))
        replace_all = bool(data.get("replace_all", False))
        target_path, err, status = validate_edit_target(target, root=request.app[APP_CFG]["root"], home=ctx.home, bridge_py=ctx.bridge_py)
        if err:
            return _json_error(ctx, err, status)
        if bool(data.get("preview", False)):
            result = ctx.create_edit_preview(target_path, old_text, new_text, replace_all=replace_all)
            status = int(result.pop("status", 200))
            if result.get("ok"):
                ctx.record_request()
            else:
                ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response(result, status=status)
        preview = ctx.create_edit_preview(target_path, old_text, new_text, replace_all=replace_all)
        if not preview.get("ok"):
            return _json_error(ctx, preview.get("error", "invalid edit"), int(preview.get("status", 400)))
        if preview.get("replacements") == 0:
            ctx.record_request()
            preview.pop("old_content", None)
            preview.pop("new_content", None)
            preview.pop("preview_id", None)
            return ctx.cors_json_response(preview)
        result = ctx.apply_edit_preview(preview["preview_id"])
        status = int(result.pop("status", 200))
        if not result.get("ok"):
            return _json_error(ctx, result.get("error", "apply failed"), status)
        ctx.audit({"type": "file_edit", "path": result["path"], "replacements": result["replacements"], "bytes": result["bytes"], "rollback_id": result["rollback_id"]})
        ctx.record_request()
        return ctx.cors_json_response(result)

    async def handle_v1_fs_edit_apply(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        try:
            data = await request.json()
        except Exception:
            return _json_error(ctx, "invalid JSON body", 400)
        preview_id = str(data.get("preview_id", "")).strip()
        if not preview_id:
            return _json_error(ctx, "missing preview_id", 400)
        result = ctx.apply_edit_preview(preview_id)
        status = int(result.pop("status", 200))
        if not result.get("ok"):
            return _json_error(ctx, result.get("error", "apply failed"), status)
        ctx.audit({"type": "file_edit", "path": result["path"], "replacements": result["replacements"], "bytes": result["bytes"], "rollback_id": result["rollback_id"]})
        ctx.record_request()
        return ctx.cors_json_response(result)

    async def handle_v1_fs_edit_rollback(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        try:
            data = await request.json()
        except Exception:
            return _json_error(ctx, "invalid JSON body", 400)
        rollback_id = str(data.get("rollback_id", "")).strip()
        if not rollback_id:
            return _json_error(ctx, "missing rollback_id", 400)
        result = ctx.rollback_edit_change(rollback_id, force=bool(data.get("force", False)))
        status = int(result.pop("status", 200))
        if not result.get("ok"):
            return _json_error(ctx, result.get("error", "rollback failed"), status)
        ctx.audit({"type": "file_edit_rollback", "path": result["path"], "rollback_id": rollback_id, "bytes": result["bytes"]})
        ctx.record_request()
        return ctx.cors_json_response(result)

    return FileHandlers(upload=handle_v1_upload, download=handle_v1_download, fs_edit=handle_v1_fs_edit, fs_edit_apply=handle_v1_fs_edit_apply, fs_edit_rollback=handle_v1_fs_edit_rollback)

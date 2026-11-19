"""Handlers for file upload/download endpoints.

v3.97.0: Migrated to @authed / err_json / parse_json_body from
arena.handler_helpers. Each handler still owns its record_request()
on the happy path (bytes+audit logic is bespoke), so we use
``auto_record=False`` — the decorator still enforces auth and
catches stray exceptions with proper error accounting.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote

from aiohttp import web

from arena.app_keys import APP_CFG
from arena.files.path_context import file_home
from arena.files.sandbox import (
    validate_download_target,
    validate_edit_target,
    validate_upload_target,
)
from arena.handler_context import FileHandlerContext
from arena.handler_helpers import authed, err_json, parse_json_body


@dataclass(frozen=True)
class FileHandlers:
    upload: Callable[..., Any]
    download: Callable[..., Any]
    fs_edit: Callable[..., Any]
    fs_edit_apply: Callable[..., Any]
    fs_edit_rollback: Callable[..., Any]


def content_disposition(name: str) -> str:
    r"""A `Content-Disposition` for a file whose name came from the filesystem.

    The name is not ours: a file called `gE\u00d7\x06` is a legal filename on POSIX
    filesystems, and putting it into a header verbatim makes
    aiohttp refuse at serialisation time -- `ValueError: Forbidden control
    character detected in headers` -- *after* the response has begun, so the
    client gets a dead connection and no status at all. The fuzzing gate found
    it on `GET /v1/download` once the jail started accepting a workspace root
    (a file under `$HOME` could always do it; the jail never made it likely).

    Two names, as RFC 6266 §4.3 asks: an ASCII fallback for clients that only
    read `filename`, and `filename*` with the real name percent-encoded, which
    cannot inject anything because everything outside the unreserved set --
    CR and LF above all -- is escaped.
    """
    fallback = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in '"\\;' else "_" for ch in name
    ) or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='', errors='surrogateescape')}"


def _json_error(ctx: FileHandlerContext, message: str, status: int) -> web.Response:
    """File-handler variant of err_json: records an error request
    for any 4xx/5xx status before returning the response.

    Kept as an internal helper because file handlers use
    ``auto_record=False`` (they record_request() themselves at
    happy-path end) — so the wrapper's automatic error accounting
    on the happy path is disabled and we need to do it explicitly
    for validation errors."""
    if status >= 400:
        ctx.record_request(is_error=True, count_request=False)
    return err_json(ctx, message, status=status)


@dataclass(frozen=True)
class EditHooks:
    """The three fs-edit callables, proven present at request time."""

    create: Callable[..., dict[str, Any]]
    apply: Callable[[str], dict[str, Any]]
    rollback: Callable[..., dict[str, Any]]


async def _handle_v1_upload(ctx: FileHandlerContext, request: web.Request) -> web.Response:
    qs = parse_qs(request.query_string)
    target = qs.get("path", [""])[0]
    target_path, err, status = validate_upload_target(
        target,
        root=request.app[APP_CFG]["root"],
        home=file_home(ctx),
        bridge_py=ctx.bridge_py,
    )
    if err:
        return _json_error(ctx, err, status)
    assert target_path is not None  # pyrefly 1.2: no union-of-tuple narrowing
    if "multipart" in request.headers.get("Content-Type", "").lower():
        return _json_error(
            ctx, "multipart/form-data not supported; use --data-binary", 400,
        )
    try:
        body = await request.read()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(body)
        ctx.audit({"type": "file_upload",
                   "path": str(target_path), "bytes": len(body)})
        ctx.record_request()
        return ctx.cors_json_response(
            {"ok": True, "path": str(target_path), "bytes": len(body)},
        )
    except Exception:
        return _json_error(ctx, "Internal error", 500)


async def _handle_v1_download(ctx: FileHandlerContext, request: web.Request) -> web.StreamResponse:
    qs = parse_qs(request.query_string)
    target = qs.get("path", [""])[0]
    target_path, err, status = validate_download_target(
        target,
        root=request.app[APP_CFG]["root"],
        home=file_home(ctx),
    )
    if err:
        return _json_error(ctx, err, status)
    assert target_path is not None  # pyrefly 1.2: no union-of-tuple narrowing
    try:
        ctx.audit({"type": "file_download",
                   "path": str(target_path),
                   "bytes": target_path.stat().st_size})
        ctx.record_request()
        return web.FileResponse(
            target_path,
            headers={
                "Content-Disposition": content_disposition(target_path.name),
                "Access-Control-Allow-Origin": "*",
            },
        )
    except Exception:
        return _json_error(ctx, "Internal error", 500)


def _edit_hooks(ctx: FileHandlerContext) -> tuple[EditHooks | None, web.Response | None]:
    """Return the wired fs-edit hooks, or a refusal response.

    The three hooks default to None on FileHandlerContext. Calling them
    unwired raised `TypeError: 'NoneType' object is not callable` inside
    the handler, which the auth wrapper turned into an opaque 500.
    """
    create = ctx.create_edit_preview
    apply_ = ctx.apply_edit_preview
    rollback = ctx.rollback_edit_change
    missing = [
        name for name, fn in (
            ("create_edit_preview", create),
            ("apply_edit_preview", apply_),
            ("rollback_edit_change", rollback),
        )
        if not callable(fn)
    ]
    if missing or create is None or apply_ is None or rollback is None:
        return None, _json_error(
            ctx, "fs edit is not available: unwired " + ", ".join(missing), 501,
        )
    return EditHooks(create=create, apply=apply_, rollback=rollback), None


async def _parse_edit_request(ctx: FileHandlerContext, request: web.Request
                                ) -> tuple[dict | None, EditHooks | None, web.Response | None]:
    data, error = await parse_json_body(request, ctx)
    if error is not None:
        ctx.record_request(is_error=True, count_request=False)
        return None, None, error
    hooks, error = _edit_hooks(ctx)
    return data, hooks, error


async def _handle_v1_fs_edit(ctx: FileHandlerContext, request: web.Request) -> web.Response:
    data, hooks, error = await _parse_edit_request(ctx, request)
    if error is not None:
        return error
    assert data is not None and hooks is not None
    target = str(data.get("path", ""))
    target_path, err, status = validate_edit_target(
        target,
        root=request.app[APP_CFG]["root"],
        home=file_home(ctx),
        bridge_py=ctx.bridge_py,
    )
    if err:
        return _json_error(ctx, err, status)
    assert target_path is not None  # pyrefly 1.2: no union-of-tuple narrowing
    return _perform_edit(ctx, hooks, target_path, data)


def _perform_edit(ctx: FileHandlerContext, hooks: EditHooks, target_path, data: dict) -> web.Response:
    old_text = str(data.get("old_text", ""))
    new_text = str(data.get("new_text", ""))
    replace_all = bool(data.get("replace_all", False))
    if bool(data.get("preview", False)):
        result = hooks.create(
            target_path, old_text, new_text, replace_all=replace_all,
        )
        status = int(result.pop("status", 200))
        if result.get("ok"):
            ctx.record_request()
        else:
            ctx.record_request(is_error=True, count_request=False)
        return ctx.cors_json_response(result, status=status)
    preview = hooks.create(
        target_path, old_text, new_text, replace_all=replace_all,
    )
    if not preview.get("ok"):
        return _json_error(
            ctx, preview.get("error", "invalid edit"),
            int(preview.get("status", 400)),
        )
    if preview.get("replacements") == 0:
        ctx.record_request()
        preview.pop("old_content", None)
        preview.pop("new_content", None)
        preview.pop("preview_id", None)
        return ctx.cors_json_response(preview)
    result = hooks.apply(preview["preview_id"])
    return _applied_edit_response(ctx, result)


def _applied_edit_response(ctx: FileHandlerContext, result: dict) -> web.Response:
    status = int(result.pop("status", 200))
    if not result.get("ok"):
        return _json_error(ctx, result.get("error", "apply failed"), status)
    ctx.audit({
        "type": "file_edit", "path": result["path"],
        "replacements": result["replacements"],
        "bytes": result["bytes"], "rollback_id": result["rollback_id"],
    })
    ctx.record_request()
    return ctx.cors_json_response(result)


async def _handle_v1_fs_edit_apply(ctx: FileHandlerContext, request: web.Request) -> web.Response:
    data, hooks, error = await _parse_edit_request(ctx, request)
    if error is not None:
        return error
    assert data is not None and hooks is not None
    preview_id = str(data.get("preview_id", "")).strip()
    if not preview_id:
        return _json_error(ctx, "missing preview_id", 400)
    result = hooks.apply(preview_id)
    return _applied_edit_response(ctx, result)


async def _handle_v1_fs_edit_rollback(ctx: FileHandlerContext, request: web.Request) -> web.Response:
    data, hooks, error = await _parse_edit_request(ctx, request)
    if error is not None:
        return error
    assert data is not None and hooks is not None
    rollback_id = str(data.get("rollback_id", "")).strip()
    if not rollback_id:
        return _json_error(ctx, "missing rollback_id", 400)
    result = hooks.rollback(
        rollback_id, force=bool(data.get("force", False)),
    )
    status = int(result.pop("status", 200))
    if not result.get("ok"):
        return _json_error(ctx, result.get("error", "rollback failed"), status)
    ctx.audit({
        "type": "file_edit_rollback", "path": result["path"],
        "rollback_id": rollback_id, "bytes": result["bytes"],
    })
    ctx.record_request()
    return ctx.cors_json_response(result)


def _bind_file_handler(ctx: FileHandlerContext, handler: Callable[..., Any]) -> Callable[..., Any]:
    @authed(ctx, auto_record=False)
    async def bound(request: web.Request) -> web.StreamResponse:
        return await handler(ctx, request)

    return bound


def make_file_handlers(ctx: FileHandlerContext) -> FileHandlers:
    return FileHandlers(
        upload=_bind_file_handler(ctx, _handle_v1_upload),
        download=_bind_file_handler(ctx, _handle_v1_download),
        fs_edit=_bind_file_handler(ctx, _handle_v1_fs_edit),
        fs_edit_apply=_bind_file_handler(ctx, _handle_v1_fs_edit_apply),
        fs_edit_rollback=_bind_file_handler(ctx, _handle_v1_fs_edit_rollback),
    )

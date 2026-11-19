"""Handlers for fs.view and fs.create REST endpoints.

These mirror the MCP ``fs.view`` and ``fs.create`` tools but return
structured JSON instead of MCP text content. They live in their own
module so ``handlers.py`` (upload/download/edit) stays under the
200-line modularity limit.

v3.97.0: Migrated to @authed / err_json / parse_json_body from
arena.handler_helpers. Each handler still records its own
happy-path request (audit + bytes/lines), so we use
``auto_record=False`` — decorator does auth + exception wrapping,
handler does happy-path accounting.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from arena.app_keys import APP_CFG
from arena.files.content_operations import _view_bounds, _write_new_content
from arena.files.path_context import file_home
from arena.files.sandbox import validate_create_target, validate_view_target
from arena.handler_context import FileHandlerContext
from arena.handler_helpers import authed, err_json, parse_json_body


@dataclass(frozen=True)
class FsViewCreateHandlers:
    view: Callable[..., Any]
    create: Callable[..., Any]


def _err(ctx, msg: str, status: int) -> web.Response:
    """Record an error request then return err_json. Because these
    handlers use auto_record=False, we book-keep 4xx/5xx errors
    explicitly."""
    ctx.record_request(is_error=True, count_request=False)
    return err_json(ctx, msg, status=status)


def _view_file(ctx: FileHandlerContext, request: web.Request, data: dict) -> web.Response:
    target = str(data.get("path", ""))
    view_range = data.get("view_range")
    target_path, err, status = validate_view_target(
        target,
        root=request.app[APP_CFG]["root"],
        home=file_home(ctx),
    )
    if err:
        return _err(ctx, err, status)
    assert target_path is not None  # pyrefly 1.2: no union-of-tuple narrowing
    try:
        content = target_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _err(ctx, "file is not valid utf-8 (binary file)", 400)
    except Exception:
        return _err(ctx, "Internal error", 500)

    lines = content.split("\n")
    total_lines = len(lines)
    try:
        start, end = _view_bounds(view_range, total_lines)
    except ValueError as exc:
        return _err(ctx, str(exc), 400)

    selected = "\n".join(lines[start - 1:end])
    ctx.audit({"type": "file_view",
                "path": str(target_path),
                "start": start, "end": end,
                "total_lines": total_lines})
    ctx.record_request()
    return ctx.cors_json_response({
        "ok": True,
        "path": str(target_path),
        "content": selected,
        "start": start,
        "end": end,
        "total_lines": total_lines,
    })


def _create_file(ctx: FileHandlerContext, request: web.Request, data: dict) -> web.Response:
    target = str(data.get("path", ""))
    content = data.get("content", "")
    if not isinstance(content, str):
        return _err(ctx, "content must be a string", 400)
    if not content:
        return _err(ctx, "missing or empty 'content'", 400)
    target_path, err, status = validate_create_target(
        target,
        root=request.app[APP_CFG]["root"],
        home=file_home(ctx),
        bridge_py=ctx.bridge_py,
    )
    if err:
        return _err(ctx, err, status)
    assert target_path is not None  # pyrefly 1.2: no union-of-tuple narrowing

    encoding = str(data.get("encoding", "")).strip().lower()
    bytes_written, problem, status = _write_new_content(target_path, content, encoding)
    if problem is not None:
        return _err(ctx, problem, status)

    ctx.audit({"type": "file_create",
                "path": str(target_path),
                "bytes": bytes_written})
    ctx.record_request()
    return ctx.cors_json_response(
        {"ok": True, "path": str(target_path), "bytes": bytes_written},
    )


def make_fs_view_create_handlers(ctx: FileHandlerContext) -> FsViewCreateHandlers:
    @authed(ctx, auto_record=False)
    async def handle_v1_fs_view(request: web.Request) -> web.Response:
        """POST /v1/fs/view — read a text file, optionally a line range."""
        data, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            ctx.record_request(is_error=True, count_request=False)
            return jerr
        assert data is not None  # the guard above already proved this
        return _view_file(ctx, request, data)

    @authed(ctx, auto_record=False)
    async def handle_v1_fs_create(request: web.Request) -> web.Response:
        """POST /v1/fs/create — create a new file (fails if it exists). Supports base64 encoding."""
        data, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            ctx.record_request(is_error=True, count_request=False)
            return jerr
        assert data is not None  # the guard above already proved this
        return _create_file(ctx, request, data)

    return FsViewCreateHandlers(
        view=handle_v1_fs_view, create=handle_v1_fs_create,
    )

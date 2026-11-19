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


def _view_bounds(view_range, total_lines: int) -> tuple[int, int]:
    """Validate the optional inclusive one-based range independently of HTTP."""
    if view_range is None:
        return 1, total_lines
    if not isinstance(view_range, list) or len(view_range) != 2:
        raise ValueError("view_range must be [start, end] line numbers (1-indexed)")
    try:
        if any(isinstance(value, bool) or
               (isinstance(value, float) and not value.is_integer()) for value in view_range):
            raise ValueError("view_range values must be integers")
        start, end = int(view_range[0]), int(view_range[1])
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("view_range values must be integers") from exc
    if start < 1 or end < 1 or start > end:
        raise ValueError(f"invalid view_range [{start}, {end}] — must be 1-indexed with start <= end")
    if start > total_lines:
        raise ValueError(f"start line {start} exceeds file length ({total_lines} lines)")
    return start, min(end, total_lines)


def make_fs_view_create_handlers(ctx: FileHandlerContext) -> FsViewCreateHandlers:
    @authed(ctx, auto_record=False)
    async def handle_v1_fs_view(request: web.Request) -> web.Response:
        """POST /v1/fs/view — read a text file, optionally a line range."""
        data, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            ctx.record_request(is_error=True, count_request=False)
            return jerr
        assert data is not None  # the guard above already proved this
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

    @authed(ctx, auto_record=False)
    async def handle_v1_fs_create(request: web.Request) -> web.Response:
        """POST /v1/fs/create — create a new file (fails if it exists). Supports base64 encoding."""
        data, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            ctx.record_request(is_error=True, count_request=False)
            return jerr
        assert data is not None  # the guard above already proved this
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
        if encoding == "base64":
            import base64
            try:
                binary_content = base64.b64decode(content.strip())
            except Exception:
                return _err(ctx, "invalid base64 content", 400)
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(binary_content)
                bytes_written = len(binary_content)
            except Exception:
                return _err(ctx, "Internal error writing binary file", 500)
        else:
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(content, encoding="utf-8")
                bytes_written = len(content.encode("utf-8"))
            except Exception:
                return _err(ctx, "Internal error", 500)

        ctx.audit({"type": "file_create",
                   "path": str(target_path),
                   "bytes": bytes_written})
        ctx.record_request()
        return ctx.cors_json_response(
            {"ok": True, "path": str(target_path), "bytes": bytes_written},
        )

    return FsViewCreateHandlers(
        view=handle_v1_fs_view, create=handle_v1_fs_create,
    )

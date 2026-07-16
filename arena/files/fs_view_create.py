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

from dataclasses import dataclass

from aiohttp import web
from arena.app_keys import APP_CFG

from arena.files.sandbox import validate_create_target, validate_view_target
from arena.handler_context import FileHandlerContext
from arena.handler_helpers import authed, err_json, parse_json_body


@dataclass(frozen=True)
class FsViewCreateHandlers:
    view: object
    create: object


def _err(ctx, msg: str, status: int) -> web.Response:
    """Record an error request then return err_json. Because these
    handlers use auto_record=False, we book-keep 4xx/5xx errors
    explicitly."""
    ctx.record_request(is_error=True, count_request=False)
    return err_json(ctx, msg, status=status)


def make_fs_view_create_handlers(ctx: FileHandlerContext) -> FsViewCreateHandlers:
    @authed(ctx, auto_record=False)
    async def handle_v1_fs_view(request: web.Request) -> web.Response:
        """POST /v1/fs/view — read a text file, optionally a line range."""
        data, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            ctx.record_request(is_error=True, count_request=False)
            return jerr
        target = str(data.get("path", ""))
        view_range = data.get("view_range")
        target_path, err, status = validate_view_target(
            target,
            root=request.app[APP_CFG]["root"],
            home=ctx.home,
        )
        if err:
            return _err(ctx, err, status)
        try:
            content = target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return _err(ctx, "file is not valid utf-8 (binary file)", 400)
        except Exception:
            return _err(ctx, "Internal error", 500)

        lines = content.split("\n")
        total_lines = len(lines)
        start, end = 1, total_lines
        if view_range is not None:
            if not isinstance(view_range, list) or len(view_range) != 2:
                return _err(
                    ctx,
                    "view_range must be [start, end] line numbers (1-indexed)",
                    400,
                )
            try:
                start, end = int(view_range[0]), int(view_range[1])
            except (ValueError, TypeError):
                return _err(ctx, "view_range values must be integers", 400)
            if start < 1 or end < 1 or start > end:
                return _err(
                    ctx,
                    f"invalid view_range [{start}, {end}] — must be "
                    f"1-indexed with start <= end",
                    400,
                )
            if start > total_lines:
                return _err(
                    ctx,
                    f"start line {start} exceeds file length "
                    f"({total_lines} lines)",
                    400,
                )
            end = min(end, total_lines)

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
        """POST /v1/fs/create — create a new text file (fails if it exists)."""
        data, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            ctx.record_request(is_error=True, count_request=False)
            return jerr
        target = str(data.get("path", ""))
        content = data.get("content", "")
        if not content:
            return _err(ctx, "missing or empty 'content'", 400)
        target_path, err, status = validate_create_target(
            target,
            root=request.app[APP_CFG]["root"],
            home=ctx.home,
            bridge_py=ctx.bridge_py,
        )
        if err:
            return _err(ctx, err, status)
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
        except Exception:
            return _err(ctx, "Internal error", 500)
        ctx.audit({"type": "file_create",
                   "path": str(target_path),
                   "bytes": len(content)})
        ctx.record_request()
        return ctx.cors_json_response(
            {"ok": True, "path": str(target_path), "bytes": len(content)},
        )

    return FsViewCreateHandlers(
        view=handle_v1_fs_view, create=handle_v1_fs_create,
    )

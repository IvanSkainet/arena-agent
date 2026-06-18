"""Handlers for fs.view and fs.create REST endpoints.

These mirror the MCP ``fs.view`` and ``fs.create`` tools but return
structured JSON instead of MCP text content. They live in their own module so
``handlers.py`` (upload/download/edit) stays under the 200-line modularity limit.
"""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.files.sandbox import validate_create_target, validate_view_target
from arena.handler_context import FileHandlerContext


@dataclass(frozen=True)
class FsViewCreateHandlers:
    view: object
    create: object


def make_fs_view_create_handlers(ctx: FileHandlerContext) -> FsViewCreateHandlers:
    async def handle_v1_fs_view(request: web.Request) -> web.Response:
        """POST /v1/fs/view - read a text file, optionally a line range."""
        r = ctx.require_auth(request)
        if r:
            return r
        try:
            data = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "invalid JSON body"}, status=400)
        target = str(data.get("path", ""))
        view_range = data.get("view_range")
        target_path, err, status = validate_view_target(
            target,
            root=request.app["cfg"]["root"],
            home=ctx.home,
        )
        if err:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": err}, status=status)
        try:
            content = target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "file is not valid utf-8 (binary file)"}, status=400)
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Internal error"}, status=500)

        lines = content.split("\n")
        total_lines = len(lines)
        start, end = 1, total_lines
        if view_range is not None:
            if not isinstance(view_range, list) or len(view_range) != 2:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "view_range must be [start, end] line numbers (1-indexed)"}, status=400)
            try:
                start, end = int(view_range[0]), int(view_range[1])
            except (ValueError, TypeError):
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "view_range values must be integers"}, status=400)
            if start < 1 or end < 1 or start > end:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": f"invalid view_range [{start}, {end}] — must be 1-indexed with start <= end"}, status=400)
            if start > total_lines:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": f"start line {start} exceeds file length ({total_lines} lines)"}, status=400)
            end = min(end, total_lines)

        selected = "\n".join(lines[start - 1:end])
        ctx.audit({"type": "file_view", "path": str(target_path), "start": start, "end": end, "total_lines": total_lines})
        ctx.record_request()
        return ctx.cors_json_response({
            "ok": True,
            "path": str(target_path),
            "content": selected,
            "start": start,
            "end": end,
            "total_lines": total_lines,
        })

    async def handle_v1_fs_create(request: web.Request) -> web.Response:
        """POST /v1/fs/create - create a new text file (fails if it exists)."""
        r = ctx.require_auth(request)
        if r:
            return r
        try:
            data = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "invalid JSON body"}, status=400)
        target = str(data.get("path", ""))
        content = data.get("content", "")
        if not content:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing or empty 'content'"}, status=400)
        target_path, err, status = validate_create_target(
            target,
            root=request.app["cfg"]["root"],
            home=ctx.home,
            bridge_py=ctx.bridge_py,
        )
        if err:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": err}, status=status)
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Internal error"}, status=500)
        ctx.audit({"type": "file_create", "path": str(target_path), "bytes": len(content)})
        ctx.record_request()
        return ctx.cors_json_response({"ok": True, "path": str(target_path), "bytes": len(content)})

    return FsViewCreateHandlers(view=handle_v1_fs_view, create=handle_v1_fs_create)

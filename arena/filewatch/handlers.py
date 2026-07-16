"""REST handlers for file watcher management."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aiohttp import web

from arena.files.sandbox import resolve_home_path
from arena.handler_context import FileWatchHandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class FileWatchHandlers:
    watch_files: object



def make_file_watch_handlers(ctx: FileWatchHandlerContext) -> FileWatchHandlers:
    @authed(ctx)
    async def handle_v1_watch_files(request: web.Request) -> web.Response:
        if request.method == "GET":
            return ctx.cors_json_response(ctx.list_sync())

        try:
            data = await request.json()
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)

        if request.method == "DELETE":
            watch_id = str(data.get("id", "")).strip()
            if not watch_id:
                return ctx.cors_json_response({"ok": False, "error": "missing id"}, status=400)
            result = ctx.remove_sync(watch_id)
            status = int(result.pop("status", 200))
            return ctx.cors_json_response(result, status=status)

        target = str(data.get("path", "")).strip()
        if not target:
            return ctx.cors_json_response({"ok": False, "error": "missing path"}, status=400)
        root = Path(request.app[ctx.app_cfg_key]["root"])
        resolved, err, status = resolve_home_path(target, root=root, home=Path(ctx.home))
        if err:
            return ctx.cors_json_response({"ok": False, "error": err}, status=status)
        result = ctx.add_sync(
            path=str(resolved),
            root=root,
            recursive=bool(data.get("recursive", True)),
            patterns=data.get("patterns") or [],
            label=str(data.get("label", "") or ""),
            created_at=ctx.utc_now(),
        )
        status = int(result.pop("status", 200))
        return ctx.cors_json_response(result, status=status)

    return FileWatchHandlers(watch_files=handle_v1_watch_files)

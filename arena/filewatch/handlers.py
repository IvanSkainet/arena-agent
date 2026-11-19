"""REST handlers for file watcher management."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from arena.files.sandbox import resolve_home_path
from arena.handler_context import FileWatchHandlerContext
from arena.handler_helpers import authed, json_object_body


@dataclass(frozen=True)
class FileWatchHandlers:
    watch_files: Callable[..., Any]



def _watch_options_error(data: dict) -> str | None:
    if not isinstance(data.get("path", ""), str):
        return "path must be a string"
    if not isinstance(data.get("recursive", True), bool):
        return "recursive must be a boolean"
    patterns = data.get("patterns", [])
    if not isinstance(patterns, list):
        return "patterns must be a list of strings"
    if not all(isinstance(pattern, str) for pattern in patterns):
        return "patterns must be a list of strings"
    return None


def _add_watch(request: web.Request, data: dict, ctx: FileWatchHandlerContext) -> web.Response:
    problem = _watch_options_error(data)
    if problem is not None:
        return ctx.cors_json_response({"ok": False, "error": problem}, status=400)
    target = data.get("path", "").strip()
    if not target:
        return ctx.cors_json_response({"ok": False, "error": "missing path"}, status=400)
    root = Path(request.app[ctx.app_cfg_key]["root"])
    resolved, err, status = resolve_home_path(target, root=root, home=Path(ctx.home))
    if err:
        return ctx.cors_json_response({"ok": False, "error": err}, status=status)
    assert resolved is not None  # the guard above already proved this
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


def make_file_watch_handlers(ctx: FileWatchHandlerContext) -> FileWatchHandlers:
    @authed(ctx)
    async def handle_v1_watch_files(request: web.Request) -> web.Response:
        if request.method == "GET":
            return ctx.cors_json_response(ctx.list_sync())

        data = await json_object_body(request)

        if request.method == "DELETE":
            watch_id = str(data.get("id", "")).strip()
            if not watch_id:
                return ctx.cors_json_response({"ok": False, "error": "missing id"}, status=400)
            result = ctx.remove_sync(watch_id)
            status = int(result.pop("status", 200))
            return ctx.cors_json_response(result, status=status)

        return _add_watch(request, data, ctx)

    return FileWatchHandlers(watch_files=handle_v1_watch_files)

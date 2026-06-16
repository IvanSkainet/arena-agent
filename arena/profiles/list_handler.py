"""Profile listing handler."""
from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web

from arena.profiles.common import auth_and_record
from arena.handler_context import ProfileHandlerContext


def _profile_summary(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "name": path.stem,
            "created": data.get("created", ""),
            "cookie_count": len(data.get("cookies", [])),
            "tab_count": len(data.get("tabs", [])),
            "has_local_storage": bool(data.get("local_storage")),
            "size_bytes": path.stat().st_size,
        }
    except Exception:
        return {"name": path.stem, "error": "corrupt profile file"}


def make_profiles_list_handler(ctx: ProfileHandlerContext):
    async def handle_v1_profiles_list(request: web.Request) -> web.Response:
        response = auth_and_record(ctx, request)
        if response:
            return response

        ctx.ensure_profiles_dir()
        profiles = [_profile_summary(path) for path in sorted(Path(ctx.profiles_dir).glob("*.json"))]
        return ctx.cors_json_response({"ok": True, "profiles": profiles, "count": len(profiles)})

    return handle_v1_profiles_list

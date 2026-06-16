"""Handlers for browser session profile save/load endpoints."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import ProfileHandlerContext
from arena.profiles.common import PROFILES_DIR, ensure_profiles_dir, sanitize_profile_name as _sanitize_profile_name
from arena.profiles.list_handler import make_profiles_list_handler
from arena.profiles.load_handler import make_profiles_load_handler
from arena.profiles.save_handler import make_profiles_save_handler


@dataclass(frozen=True)
class ProfileHandlers:
    profiles: object
    load: object


def make_profile_handlers(ctx: ProfileHandlerContext) -> ProfileHandlers:
    list_handler = make_profiles_list_handler(ctx)
    save_handler = make_profiles_save_handler(ctx)

    async def handle_v1_profiles(request: web.Request) -> web.Response:
        """GET /v1/profiles — list profiles. POST /v1/profiles — save current session."""
        if request.method == "GET":
            return await list_handler(request)
        if request.method == "POST":
            return await save_handler(request)
        return ctx.cors_json_response({"ok": False, "error": "method not supported"}, status=405)

    return ProfileHandlers(
        profiles=handle_v1_profiles,
        load=make_profiles_load_handler(ctx),
    )


__all__ = ["PROFILES_DIR", "ProfileHandlers", "_sanitize_profile_name", "ensure_profiles_dir", "make_profile_handlers"]

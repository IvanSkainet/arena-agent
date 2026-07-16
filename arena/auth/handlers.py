"""User-management API handlers."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web
from arena.app_keys import APP_CFG

from arena.handler_context import UserHandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class UserHandlers:
    users: object


def make_user_handlers(ctx: UserHandlerContext) -> UserHandlers:
    @authed(ctx)
    async def handle_v1_users(request: web.Request) -> web.Response:
        is_auth, role = ctx.check_auth_with_role(request)
        if not is_auth or role != "admin":
            return ctx.cors_json_response({"ok": False, "error": "admin role required"}, status=403)

        if request.method == "GET":
            user_list = ctx.list_users(request.app[APP_CFG]["token"])
            return ctx.cors_json_response({"ok": True, "users": user_list, "count": len(user_list)})

        if request.method == "POST":
            try:
                data = await request.json()
                name = data.get("name", "")
                new_token = data.get("token", "") or ctx.token_generator(24)
                new_role = data.get("role", "user")
                if new_role not in ("admin", "user", "readonly"):
                    return ctx.cors_json_response({"ok": False, "error": "role must be admin, user, or readonly"}, status=400)
                if not name:
                    return ctx.cors_json_response({"ok": False, "error": "name is required"}, status=400)
                ctx.add_or_update_user(name=name, token=new_token, role=new_role)
                ctx.audit({"type": "user_add", "name": name, "role": new_role})
                ctx.log_info("[Auth] User %s added/updated with role %s", name, new_role)
                return ctx.cors_json_response({"ok": True, "name": name, "role": new_role, "token": new_token, "note": "Save this token — it won't be shown again"})
            except Exception as exc:
                return ctx.cors_json_response({"ok": False, "error": str(exc)}, status=400)

        if request.method == "DELETE":
            try:
                data = await request.json()
                name = data.get("name", "")
                if not name:
                    return ctx.cors_json_response({"ok": False, "error": "name is required"}, status=400)
                if not ctx.remove_user(name):
                    return ctx.cors_json_response({"ok": False, "error": f"user {name} not found"}, status=404)
                ctx.audit({"type": "user_remove", "name": name})
                ctx.log_info("[Auth] User %s removed", name)
                return ctx.cors_json_response({"ok": True, "removed": name})
            except Exception as exc:
                return ctx.cors_json_response({"ok": False, "error": str(exc)}, status=400)

        return ctx.cors_json_response({"ok": False, "error": "method not supported"}, status=405)

    return UserHandlers(users=handle_v1_users)

"""Cookie profile handlers for CDP cookie storage."""
from __future__ import annotations

from arena.browser.cdp.cookie_common import (
    auth_and_record,
    get_cookie_manager_or_response,
    require_cdp_connected,
)
from arena.handler_context import CdpCookiesHandlerContext


def make_cdp_cookies_profiles_handler(ctx: CdpCookiesHandlerContext):
    async def handle_v1_cdp_cookies_profiles(request):
        """GET/POST /v1/browser/cdp/cookies/profiles — Manage cookie profiles."""
        response = auth_and_record(ctx, request)
        if response:
            return response
        response = require_cdp_connected(ctx)
        if response:
            return response

        if request.method == "GET":
            cookie_mgr = ctx.cdp_state.get("cookie_mgr")
            profiles = cookie_mgr.list_profiles() if cookie_mgr else []
            profile_info = []
            for name in profiles:
                info = cookie_mgr.get_profile_info(name) if cookie_mgr else None
                profile_info.append(info or {"name": name})

            return ctx.cors_json_response({
                "ok": True,
                "profiles": profile_info,
                "count": len(profile_info),
            })

        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

        action = body.get("action")
        name = body.get("name")
        if not action or not name:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'action' or 'name'"}, status=400)

        try:
            cookie_mgr, response = await get_cookie_manager_or_response(ctx)
            if response:
                return response

            if action == "save":
                count = await cookie_mgr.save_profile(name, domain_filter=body.get("domain"))
                return ctx.cors_json_response({
                    "ok": True,
                    "action": "save",
                    "profile": name,
                    "cookie_count": count,
                })
            if action == "restore":
                count = await cookie_mgr.restore_profile(
                    name,
                    clear_first=body.get("clear_first", True),
                )
                return ctx.cors_json_response({
                    "ok": True,
                    "action": "restore",
                    "profile": name,
                    "restored_count": count,
                })
            if action == "delete":
                deleted = cookie_mgr.delete_profile(name)
                return ctx.cors_json_response({
                    "ok": deleted,
                    "action": "delete",
                    "profile": name,
                })

            return ctx.cors_json_response(
                {"ok": False, "error": f"Unknown action '{action}'. Use save, restore, or delete."},
                status=400,
            )
        except KeyError as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=404)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return handle_v1_cdp_cookies_profiles

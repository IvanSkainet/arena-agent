"""Profile load/restore handler."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp import web

from arena.profiles.common import auth_and_record, sanitize_profile_name
from arena.handler_context import ProfileHandlerContext


async def _restore_cookies(ctx: ProfileHandlerContext, cookies: list) -> int:
    restored = 0
    if not cookies:
        return restored
    tab, _err = await ctx.cdp_active_tab()
    if not tab:
        return restored
    for cookie in cookies:
        try:
            await asyncio.wait_for(tab.set_cookie(cookie), timeout=5)
            restored += 1
        except Exception:
            pass
    return restored


async def _restore_tabs(ctx: ProfileHandlerContext, tabs: list) -> int:
    restored = 0
    if not tabs:
        return restored
    tab_nav, _nav_err = await ctx.cdp_active_tab()
    if not tab_nav:
        return restored
    for tab_info in tabs:
        url = tab_info.get("url", "")
        if url:
            try:
                await asyncio.wait_for(tab_nav.navigate(url), timeout=10)
                restored += 1
            except Exception:
                pass
    return restored


async def _restore_local_storage(ctx: ProfileHandlerContext, local_storage: dict) -> bool:
    if not local_storage:
        return False
    tab, _err = await ctx.cdp_active_tab()
    if not tab:
        return False
    try:
        pairs = [f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)})" for k, v in local_storage.items()]
        script = ";".join(pairs[:100])
        await asyncio.wait_for(tab.eval_js(script), timeout=5)
        return True
    except Exception:
        return False


def make_profiles_load_handler(ctx: ProfileHandlerContext):
    async def handle_v1_profiles_load(request: web.Request) -> web.Response:
        """POST /v1/profiles/{name}/load — Load a browser session profile."""
        response = auth_and_record(ctx, request)
        if response:
            return response

        name = request.match_info.get("name", "")
        if not name:
            return ctx.cors_json_response({"ok": False, "error": "profile name required"}, status=400)

        name = sanitize_profile_name(name)
        profile_path = Path(ctx.profiles_dir) / f"{name}.json"
        if not profile_path.exists():
            return ctx.cors_json_response({"ok": False, "error": f"profile {name} not found"}, status=404)

        try:
            profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": f"corrupt profile: {e}"}, status=500)

        if not ctx.cdp_state.get("connected") or not ctx.cdp_state.get("manager"):
            return ctx.cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)

        restored = {"cookies": 0, "tabs": 0, "local_storage": False}
        try:
            restored["cookies"] = await _restore_cookies(ctx, profile_data.get("cookies", []))
            restored["tabs"] = await _restore_tabs(ctx, profile_data.get("tabs", []))
            restored["local_storage"] = await _restore_local_storage(ctx, profile_data.get("local_storage", {}))

            ctx.audit({"type": "profile_load", "name": name, "restored": restored})
            await ctx.emit_event("profile_loaded", {"name": name, "restored": restored})

            return ctx.cors_json_response({
                "ok": True,
                "name": name,
                "restored": restored,
                "cookie_count": len(profile_data.get("cookies", [])),
                "tab_count": len(profile_data.get("tabs", [])),
            })
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return handle_v1_profiles_load

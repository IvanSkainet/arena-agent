"""Profile save handler."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from arena.profiles.common import auth_and_record, sanitize_profile_name
from arena.handler_context import ProfileHandlerContext


async def _save_cookies(ctx: ProfileHandlerContext, profile_data: dict[str, Any]) -> None:
    try:
        tab, _err = await ctx.cdp_active_tab()
        if tab:
            cookie_result = await asyncio.wait_for(tab.get_cookies(), timeout=10)
            profile_data["cookies"] = cookie_result if isinstance(cookie_result, list) else []
    except Exception as e:
        profile_data["cookies"] = []
        ctx.log_warning("[Profiles] Failed to save cookies: %s", e)


async def _save_tabs(ctx: ProfileHandlerContext, mgr, profile_data: dict[str, Any]) -> None:
    try:
        tabs_info = []
        if mgr.active_tab:
            try:
                eval_result = await asyncio.wait_for(
                    mgr.active_tab.eval_js("JSON.stringify({url: location.href, title: document.title})"),
                    timeout=5,
                )
                if eval_result:
                    tab_data = json.loads(eval_result) if isinstance(eval_result, str) else {}
                    tabs_info.append(tab_data)
            except Exception:
                pass
        profile_data["tabs"] = tabs_info
    except Exception as e:
        profile_data["tabs"] = []
        ctx.log_warning("[Profiles] Failed to save tabs: %s", e)


async def _save_local_storage(ctx: ProfileHandlerContext, profile_data: dict[str, Any]) -> None:
    try:
        tab, _err = await ctx.cdp_active_tab()
        if tab:
            ls_result = await asyncio.wait_for(
                tab.eval_js("JSON.stringify(Object.fromEntries(Object.entries(localStorage)))"),
                timeout=5,
            )
            profile_data["local_storage"] = json.loads(ls_result) if isinstance(ls_result, str) else {}
    except Exception as e:
        profile_data["local_storage"] = {}
        ctx.log_warning("[Profiles] Failed to save localStorage: %s", e)


async def _parse_save_request(request: web.Request) -> tuple[str, bool, bool, bool]:
    data = await request.json()
    profile_name = sanitize_profile_name(data.get("name", f"profile_{int(time.time())}"))
    return (
        profile_name,
        data.get("cookies", True),
        data.get("tabs", True),
        data.get("local_storage", False),
    )


def make_profiles_save_handler(ctx: ProfileHandlerContext):
    async def handle_v1_profiles_save(request: web.Request) -> web.Response:
        response = auth_and_record(ctx, request)
        if response:
            return response

        try:
            profile_name, save_cookies, save_tabs, save_local_storage = await _parse_save_request(request)
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)

        if not ctx.cdp_state.get("connected") or not ctx.cdp_state.get("manager"):
            return ctx.cors_json_response({"ok": False, "error": "CDP not connected. Connect first."}, status=400)

        mgr = ctx.cdp_state["manager"]
        profile_data: dict[str, Any] = {"created": ctx.utc_now(), "name": profile_name, "version": ctx.version}

        try:
            if save_cookies:
                await _save_cookies(ctx, profile_data)
            if save_tabs:
                await _save_tabs(ctx, mgr, profile_data)
            if save_local_storage:
                await _save_local_storage(ctx, profile_data)

            ctx.ensure_profiles_dir()
            profile_path = Path(ctx.profiles_dir) / f"{profile_name}.json"
            profile_path.write_text(json.dumps(profile_data, indent=2, ensure_ascii=False))

            ctx.audit({
                "type": "profile_save",
                "name": profile_name,
                "cookies": len(profile_data.get("cookies", [])),
                "tabs": len(profile_data.get("tabs", [])),
            })
            await ctx.emit_event("profile_saved", {"name": profile_name})

            return ctx.cors_json_response({
                "ok": True,
                "name": profile_name,
                "cookie_count": len(profile_data.get("cookies", [])),
                "tab_count": len(profile_data.get("tabs", [])),
                "has_local_storage": bool(profile_data.get("local_storage")),
            })
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return handle_v1_profiles_save

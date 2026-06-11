"""Handlers for browser session profile save/load endpoints."""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from arena.constants import APP_DIR
from arena.handler_context import ProfileHandlerContext

PROFILES_DIR = APP_DIR / "profiles"


@dataclass(frozen=True)
class ProfileHandlers:
    profiles: object
    load: object


def ensure_profiles_dir() -> Path:
    """Ensure profiles directory exists."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILES_DIR


def _sanitize_profile_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-.]", "_", name)


def make_profile_handlers(ctx: ProfileHandlerContext) -> ProfileHandlers:
    async def handle_v1_profiles(request: web.Request) -> web.Response:
        """GET /v1/profiles — List browser session profiles.
        POST /v1/profiles — Save current browser session as profile.
        """
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        if request.method == "GET":
            ctx.ensure_profiles_dir()
            profiles = []
            for p in sorted(Path(ctx.profiles_dir).glob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    profiles.append({
                        "name": p.stem,
                        "created": data.get("created", ""),
                        "cookie_count": len(data.get("cookies", [])),
                        "tab_count": len(data.get("tabs", [])),
                        "has_local_storage": bool(data.get("local_storage")),
                        "size_bytes": p.stat().st_size,
                    })
                except Exception:
                    profiles.append({"name": p.stem, "error": "corrupt profile file"})

            return ctx.cors_json_response({"ok": True, "profiles": profiles, "count": len(profiles)})

        if request.method == "POST":
            try:
                data = await request.json()
                profile_name = data.get("name", f"profile_{int(time.time())}")
                # Sanitize name.
                profile_name = _sanitize_profile_name(profile_name)
                save_cookies = data.get("cookies", True)
                save_tabs = data.get("tabs", True)
                save_local_storage = data.get("local_storage", False)
            except Exception as e:
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)

            # Need an active CDP connection.
            if not ctx.cdp_state.get("connected") or not ctx.cdp_state.get("manager"):
                return ctx.cors_json_response({"ok": False, "error": "CDP not connected. Connect first."}, status=400)

            mgr = ctx.cdp_state["manager"]
            profile_data: dict[str, Any] = {"created": ctx.utc_now(), "name": profile_name, "version": ctx.version}

            try:
                # Save cookies.
                if save_cookies:
                    try:
                        tab, err = await ctx.cdp_active_tab()
                        if tab:
                            cookie_result = await asyncio.wait_for(tab.get_cookies(), timeout=10)
                            profile_data["cookies"] = cookie_result if isinstance(cookie_result, list) else []
                    except Exception as e:
                        profile_data["cookies"] = []
                        ctx.log_warning("[Profiles] Failed to save cookies: %s", e)

                # Save tabs info.
                if save_tabs:
                    try:
                        tabs_info = []
                        if mgr.active_tab:
                            # Get current tab URL and title.
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

                # Save localStorage.
                if save_local_storage:
                    try:
                        tab, err = await ctx.cdp_active_tab()
                        if tab:
                            ls_result = await asyncio.wait_for(
                                tab.eval_js("JSON.stringify(Object.fromEntries(Object.entries(localStorage)))"),
                                timeout=5,
                            )
                            profile_data["local_storage"] = json.loads(ls_result) if isinstance(ls_result, str) else {}
                    except Exception as e:
                        profile_data["local_storage"] = {}
                        ctx.log_warning("[Profiles] Failed to save localStorage: %s", e)

                # Write profile.
                ctx.ensure_profiles_dir()
                profile_path = Path(ctx.profiles_dir) / f"{profile_name}.json"
                profile_path.write_text(json.dumps(profile_data, indent=2, ensure_ascii=False))

                ctx.audit({"type": "profile_save", "name": profile_name,
                           "cookies": len(profile_data.get("cookies", [])),
                           "tabs": len(profile_data.get("tabs", []))})
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

        return ctx.cors_json_response({"ok": False, "error": "method not supported"}, status=405)

    async def handle_v1_profiles_load(request: web.Request) -> web.Response:
        """POST /v1/profiles/{name}/load — Load a browser session profile."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        name = request.match_info.get("name", "")
        if not name:
            return ctx.cors_json_response({"ok": False, "error": "profile name required"}, status=400)

        # Sanitize.
        name = _sanitize_profile_name(name)
        profile_path = Path(ctx.profiles_dir) / f"{name}.json"

        if not profile_path.exists():
            return ctx.cors_json_response({"ok": False, "error": f"profile {name} not found"}, status=404)

        try:
            profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": f"corrupt profile: {e}"}, status=500)

        # Need active CDP connection.
        if not ctx.cdp_state.get("connected") or not ctx.cdp_state.get("manager"):
            return ctx.cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)

        restored = {"cookies": 0, "tabs": 0, "local_storage": False}

        try:
            # Restore cookies.
            cookies = profile_data.get("cookies", [])
            if cookies:
                tab, err = await ctx.cdp_active_tab()
                if tab:
                    for cookie in cookies:
                        try:
                            await asyncio.wait_for(tab.set_cookie(cookie), timeout=5)
                            restored["cookies"] += 1
                        except Exception:
                            pass

            # Restore tabs.
            tabs = profile_data.get("tabs", [])
            if tabs:
                tab_nav, nav_err = await ctx.cdp_active_tab()
                if tab_nav:
                    for tab_info in tabs:
                        url = tab_info.get("url", "")
                        if url:
                            try:
                                await asyncio.wait_for(tab_nav.navigate(url), timeout=10)
                                restored["tabs"] += 1
                            except Exception:
                                pass

            # Restore localStorage.
            ls = profile_data.get("local_storage", {})
            if ls:
                tab, err = await ctx.cdp_active_tab()
                if tab:
                    try:
                        pairs = [f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)})" for k, v in ls.items()]
                        script = ";".join(pairs[:100])  # Limit to 100 items.
                        await asyncio.wait_for(tab.eval_js(script), timeout=5)
                        restored["local_storage"] = True
                    except Exception:
                        pass

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

    return ProfileHandlers(profiles=handle_v1_profiles, load=handle_v1_profiles_load)

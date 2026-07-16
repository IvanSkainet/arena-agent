"""Handlers for skills endpoints."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import SkillHandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class SkillHandlers:
    skills: object
    install: object
    uninstall: object
    run: object
    reload: object


def make_skill_handlers(ctx: SkillHandlerContext) -> SkillHandlers:
    @authed(ctx)
    async def handle_v1_skills(request: web.Request) -> web.Response:
        """GET /v1/skills — List skills."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.skills_list_with_cache)
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_skills_reload(request: web.Request) -> web.Response:
        """POST /v1/skills/reload — Force reload skills cache."""
        ctx.skills_cache_reset()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.skills_list_with_cache)
        ctx.log_info("[Skills] Hot-reload: %d skills scanned", result.get("count", 0))
        return ctx.cors_json_response({
            "ok": True,
            "reloaded": True,
            "count": result.get("count", 0),
            "skills": result.get("skills", []),
        })

    @authed(ctx)
    async def handle_v1_skills_install(request: web.Request) -> web.Response:
        """POST /v1/skills/install — Install a third-party skill from git or zip."""
        data = await request.json()
        name = str(data.get("name", "")).strip()
        url = str(data.get("url", "")).strip()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.skill_install_sync, name, url)
        if result.get("ok"):
            ctx.audit({"type": "skill_installed", "name": name, "url": url})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_skills_uninstall(request: web.Request) -> web.Response:
        """POST /v1/skills/uninstall — Uninstall a third-party skill."""
        data = await request.json()
        name = str(data.get("name", "")).strip()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.skill_uninstall_sync, name)
        if result.get("ok"):
            ctx.audit({"type": "skill_uninstalled", "name": name})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_skills_run(request: web.Request) -> web.Response:
        """POST /v1/skills/run — Run a skill."""
        try:
            data = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        name = data.get("name", "")
        if not name:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing name"}, status=400)
        if ".." in name or "\\" in name:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "invalid skill name"}, status=400)
        if "/" in name and not ctx.skill_path_is_safe(name):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "invalid skill name"}, status=400)

        skill_args = data.get("args") or []
        skill_input = data.get("input") or {}
        if skill_input and not skill_args:
            if "action" in skill_input and "url" in skill_input:
                skill_args = [skill_input["action"], skill_input["url"]]
            elif "url" in skill_input and "task" in skill_input:
                skill_args = ["extract", skill_input["url"], "--task", skill_input["task"]]
            elif "url" in skill_input:
                skill_args = ["open", skill_input["url"]]
            elif "query" in skill_input:
                skill_args = [skill_input["query"]]
                if "n" in skill_input:
                    skill_args.append(str(skill_input["n"]))

        env_extra = {}
        if skill_input:
            env_extra["SKILL_INPUT"] = json.dumps(skill_input)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.skills_run_sync, name, skill_args, env_extra)
        ctx.audit({"type": "skill_run", "name": name, "args": skill_args, "ok": result.get("ok", False)})
        return ctx.cors_json_response(result)

    return SkillHandlers(
        skills=handle_v1_skills,
        install=handle_v1_skills_install,
        uninstall=handle_v1_skills_uninstall,
        run=handle_v1_skills_run,
        reload=handle_v1_skills_reload,
    )

"""Resource listing and mission-management runtime compatibility wrappers."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.resources.listing import list_agents, list_hooks, list_missions, list_reports, list_subagents, show_mission
from arena.resources.mission_state import get_mission_report, get_mission_status
from arena.resources.missions_manage import compose_mission_draft, create_mission_from_draft, list_mission_templates, run_mission
from arena.resources.subagents import spawn_subagent


@dataclass(frozen=True)
class ResourceRuntimeContext:
    missions_dir: Path
    reports_dir: Path
    hooks_dir: Path
    agents_dir: Path
    subagents_dir: Path
    bin_dir: Path | str
    root_agent: Path
    build_plan: Callable[..., dict[str, Any]]
    subprocess_kwargs: Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class ResourceRuntime:
    list_missions_sync: Callable[[], list[dict[str, Any]]]
    list_reports_sync: Callable[[], list[dict[str, Any]]]
    hooks_list_sync: Callable[[], dict[str, Any]]
    agents_list_sync: Callable[[], dict[str, Any]]
    subagents_list_sync: Callable[[], dict[str, Any]]
    subagents_spawn_sync: Callable[[dict[str, Any]], dict[str, Any]]
    mission_show_sync: Callable[[str], dict[str, Any]]
    mission_status_sync: Callable[[str], dict[str, Any]]
    mission_report_sync: Callable[[str], dict[str, Any]]
    mission_templates_sync: Callable[[], dict[str, Any]]
    mission_compose_sync: Callable[[dict[str, Any]], dict[str, Any]]
    mission_create_sync: Callable[[dict[str, Any]], dict[str, Any]]
    mission_run_sync: Callable[[dict[str, Any]], dict[str, Any]]



def make_resource_runtime(ctx: ResourceRuntimeContext) -> ResourceRuntime:
    def _list_missions_sync() -> list[dict[str, Any]]:
        return list_missions(ctx.missions_dir)

    def _list_reports_sync() -> list[dict[str, Any]]:
        return list_reports(ctx.reports_dir)

    def _hooks_list_sync() -> dict[str, Any]:
        return list_hooks(ctx.hooks_dir)

    def _agents_list_sync() -> dict[str, Any]:
        return list_agents(ctx.agents_dir)

    def _subagents_list_sync() -> dict[str, Any]:
        return list_subagents(ctx.subagents_dir)

    def _subagents_spawn_sync(data: dict[str, Any]) -> dict[str, Any]:
        return spawn_subagent(data, bin_dir=ctx.bin_dir, subprocess_kwargs_fn=ctx.subprocess_kwargs)

    def _mission_show_sync(name: str) -> dict[str, Any]:
        return show_mission(ctx.missions_dir, name)

    def _mission_status_sync(name: str) -> dict[str, Any]:
        return get_mission_status(ctx.missions_dir, name)

    def _mission_report_sync(name: str) -> dict[str, Any]:
        return get_mission_report(ctx.missions_dir, name)

    def _mission_templates_sync() -> dict[str, Any]:
        return list_mission_templates()

    def _mission_compose_sync(data: dict[str, Any]) -> dict[str, Any]:
        return compose_mission_draft(goal=str(data.get("goal", "") or ""), context=str(data.get("context", "") or ""), constraints=data.get("constraints") or [], max_steps=int(data.get("max_steps", 8) or 8), memory_profile=data.get("memory_profile"), title=str(data.get("title", "") or ""), template=str(data.get("template", "") or ""), build_plan=ctx.build_plan)

    def _mission_create_sync(data: dict[str, Any]) -> dict[str, Any]:
        composed = data.get("draft") if isinstance(data.get("draft"), dict) else _mission_compose_sync(data).get("draft")
        if not composed:
            return {"ok": False, "error": "failed to compose mission", "status": 400}
        return create_mission_from_draft(missions_dir=ctx.missions_dir, draft=composed, mission_id=str(data.get("mission_id", "") or ""), overwrite=bool(data.get("overwrite", False)))

    def _mission_run_sync(data: dict[str, Any]) -> dict[str, Any]:
        return run_mission(root_agent=ctx.root_agent, mission_id=str(data.get("mission_id", "") or data.get("id", "") or ""), step=int(data["step"]) if data.get("step") is not None else None, timeout=int(data.get("timeout", 180) or 180), subprocess_kwargs=ctx.subprocess_kwargs)

    return ResourceRuntime(list_missions_sync=_list_missions_sync, list_reports_sync=_list_reports_sync, hooks_list_sync=_hooks_list_sync, agents_list_sync=_agents_list_sync, subagents_list_sync=_subagents_list_sync, subagents_spawn_sync=_subagents_spawn_sync, mission_show_sync=_mission_show_sync, mission_status_sync=_mission_status_sync, mission_report_sync=_mission_report_sync, mission_templates_sync=_mission_templates_sync, mission_compose_sync=_mission_compose_sync, mission_create_sync=_mission_create_sync, mission_run_sync=_mission_run_sync)

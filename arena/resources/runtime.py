"""Resource listing runtime compatibility wrappers."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.resources.listing import list_agents, list_hooks, list_missions, list_reports, list_subagents, show_mission
from arena.resources.subagents import spawn_subagent


@dataclass(frozen=True)
class ResourceRuntimeContext:
    missions_dir: Path
    reports_dir: Path
    hooks_dir: Path
    agents_dir: Path
    subagents_dir: Path
    bin_dir: Path | str
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

    return ResourceRuntime(
        list_missions_sync=_list_missions_sync,
        list_reports_sync=_list_reports_sync,
        hooks_list_sync=_hooks_list_sync,
        agents_list_sync=_agents_list_sync,
        subagents_list_sync=_subagents_list_sync,
        subagents_spawn_sync=_subagents_spawn_sync,
        mission_show_sync=_mission_show_sync,
    )

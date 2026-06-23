"""Mission/resource wiring helpers for transitional bridge registries."""
from __future__ import annotations

from typing import Any


def build_resource_registry(env, registry: dict[str, Any]) -> None:
    def _mission_propose_sync(data: dict[str, Any]) -> dict[str, Any]:
        return env.propose_mission_bundle(
            goal=str(data.get("goal", "") or ""),
            context=str(data.get("context", "") or ""),
            constraints=data.get("constraints") or [],
            max_steps=int(data.get("max_steps", 8) or 8),
            max_iterations=int(data.get("max_iterations", 4) or 4),
            memory_profile=data.get("memory_profile"),
            url=str(data.get("url", "") or ""),
            template=str(data.get("template", "") or ""),
            title=str(data.get("title", "") or ""),
            notes=str(data.get("notes", "") or ""),
            create=bool(data.get("create", False)),
            mission_id=str(data.get("mission_id", "") or ""),
            overwrite=bool(data.get("overwrite", False)),
            run_now=bool(data.get("run_now", False)),
            timeout=int(data.get("timeout", 180) or 180),
            react_sync=registry["_react_sync"],
            reflect_sync=registry["_reflect_sync"],
            compose_sync=env._resource_runtime.mission_compose_sync,
            create_sync=env._resource_runtime.mission_create_sync,
            run_sync=env._resource_runtime.mission_run_sync,
        )

    def _mission_recover_sync(data: dict[str, Any]) -> dict[str, Any]:
        return env.recover_mission_bundle(
            missions_dir=env._resource_runtime_ctx.missions_dir,
            mission_id=str(data.get("mission_id", "") or data.get("id", "") or ""),
            notes=str(data.get("notes", "") or ""),
            failed_only=bool(data.get("failed_only", True)),
            step=int(data["step"]) if data.get("step") is not None else None,
            timeout=int(data.get("timeout", 180) or 180),
            rerun_now=bool(data.get("rerun_now", False)),
            compose_followup=bool(data.get("compose_followup", False)),
            create_followup=bool(data.get("create_followup", False)),
            followup_goal=str(data.get("followup_goal", "") or ""),
            followup_title=str(data.get("followup_title", "") or ""),
            followup_mission_id=str(data.get("followup_mission_id", "") or ""),
            max_steps=int(data.get("max_steps", 8) or 8),
            memory_profile=data.get("memory_profile"),
            template=str(data.get("template", "") or ""),
            overwrite=bool(data.get("overwrite", False)),
            reflect_sync=registry["_reflect_sync"],
            compose_sync=env._resource_runtime.mission_compose_sync,
            create_sync=env._resource_runtime.mission_create_sync,
            rerun_sync=env._resource_runtime.mission_rerun_sync,
        )

    rr = env._resource_runtime
    registry.update({
        "_hooks_list_sync": rr.hooks_list_sync,
        "_agents_list_sync": rr.agents_list_sync,
        "_subagents_list_sync": rr.subagents_list_sync,
        "_subagents_spawn_sync": rr.subagents_spawn_sync,
        "_mission_show_sync": rr.mission_show_sync,
        "_mission_status_sync": rr.mission_status_sync,
        "_mission_report_sync": rr.mission_report_sync,
        "_mission_history_sync": rr.mission_history_sync,
        "_mission_catalog_sync": rr.mission_catalog_sync,
        "_mission_templates_sync": rr.mission_templates_sync,
        "_mission_compose_sync": rr.mission_compose_sync,
        "_mission_propose_sync": _mission_propose_sync,
        "_mission_create_sync": rr.mission_create_sync,
        "_mission_run_sync": rr.mission_run_sync,
        "_mission_rerun_sync": rr.mission_rerun_sync,
        "_mission_recover_sync": _mission_recover_sync,
    })
    resource_handler_ctx = env.ResourceHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        list_missions_sync=env._list_missions_sync,
        list_reports_sync=env._list_reports_sync,
        hooks_list_sync=registry["_hooks_list_sync"],
        agents_list_sync=registry["_agents_list_sync"],
        subagents_list_sync=registry["_subagents_list_sync"],
        mission_show_sync=registry["_mission_show_sync"],
        mission_status_sync=registry["_mission_status_sync"],
        mission_report_sync=registry["_mission_report_sync"],
        mission_history_sync=registry["_mission_history_sync"],
        mission_catalog_sync=registry["_mission_catalog_sync"],
        mission_templates_sync=registry["_mission_templates_sync"],
        mission_compose_sync=registry["_mission_compose_sync"],
        mission_propose_sync=registry["_mission_propose_sync"],
        mission_create_sync=registry["_mission_create_sync"],
        mission_run_sync=registry["_mission_run_sync"],
        mission_rerun_sync=registry["_mission_rerun_sync"],
        mission_recover_sync=registry["_mission_recover_sync"],
        subagent_spawn_sync=registry["_subagents_spawn_sync"],
        audit=env.audit,
    )
    resource_handlers = env.make_resource_handlers(resource_handler_ctx)
    env.export_handler_attrs(registry, resource_handlers, {
        "handle_v1_missions": "missions",
        "handle_v1_reports": "reports",
        "handle_v1_hooks": "hooks",
        "handle_v1_agents": "agents",
        "handle_v1_subagents": "subagents",
        "handle_v1_subagents_spawn": "subagents_spawn",
        "handle_v1_mission_show": "mission_show",
        "handle_v1_mission_status": "mission_status",
        "handle_v1_mission_report": "mission_report",
        "handle_v1_mission_history": "mission_history",
        "handle_v1_mission_catalog": "mission_catalog",
        "handle_v1_mission_templates": "mission_templates",
        "handle_v1_mission_compose": "mission_compose",
        "handle_v1_mission_propose": "mission_propose",
        "handle_v1_mission_create": "mission_create",
        "handle_v1_mission_run": "mission_run",
        "handle_v1_mission_rerun": "mission_rerun",
        "handle_v1_mission_recover": "mission_recover",
    })
    registry.update({"_resource_handler_ctx": resource_handler_ctx, "_resource_handlers": resource_handlers})


__all__ = ["build_resource_registry"]

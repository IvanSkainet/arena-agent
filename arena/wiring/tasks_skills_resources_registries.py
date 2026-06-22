"""task, skill and resource handler/runtime wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Callable

from arena.app_keys import APP_CFG
from arena.wiring.env import RuntimeEnv


def build_tasks_skills_resources_registries(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build task queue, skill and resource compatibility globals/handlers."""
    env = RuntimeEnv(g)
    registry: dict[str, Any] = {}

    task_queue_runtime_ctx = env.TaskQueueRuntimeContext(
        inbox=env.INBOX,
        running=env.RUNNING,
        done=env.DONE,
        failed=env.FAILED,
        default_cwd=str(Path.home()),
        now=env.utc_now,
    )
    task_queue_runtime = env.make_task_queue_runtime(task_queue_runtime_ctx)
    registry.update({
        "_task_queue_runtime_ctx": task_queue_runtime_ctx,
        "_task_queue_runtime": task_queue_runtime,
        "_tasks_list_sync": task_queue_runtime.tasks_list_sync,
        "_task_submit_sync": task_queue_runtime.task_submit_sync,
        "_tasks_clean_sync": task_queue_runtime.tasks_clean_sync,
    })

    task_handler_ctx = env.TaskHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        tasks_list_sync=registry["_tasks_list_sync"],
        task_submit_sync=registry["_task_submit_sync"],
        tasks_clean_sync=registry["_tasks_clean_sync"],
        audit=env.audit,
    )
    task_handlers = env.make_task_handlers(task_handler_ctx)
    env.export_handler_attrs(registry, task_handlers, {"handle_v1_tasks_get": "tasks_get", "handle_v1_tasks_post": "tasks_post", "handle_v1_tasks_clean": "tasks_clean"})
    registry.update({"_task_handler_ctx": task_handler_ctx, "_task_handlers": task_handlers})

    skill_runtime_ctx = env.SkillRuntimeContext(
        skills_dir=lambda: g["SKILLS_DIR"],
        root_agent=lambda: g["ROOT_AGENT"],
        bin_dir=lambda: g["BIN"],
        subprocess_kwargs=env._subprocess_kwargs,
    )
    skill_runtime = env.make_skill_runtime(skill_runtime_ctx)
    registry.update({
        "_skill_runtime_ctx": skill_runtime_ctx,
        "_skill_runtime": skill_runtime,
        "_skills_list_sync": skill_runtime.skills_list_sync,
        "_parse_skill_folder": skill_runtime.parse_skill_folder_compat,
        "_skill_install_sync": skill_runtime.skill_install_sync,
        "_normalize_third_party_skill_name": skill_runtime.normalize_third_party_skill_name,
        "_skill_uninstall_sync": skill_runtime.skill_uninstall_sync,
        "_skills_run_sync": skill_runtime.skills_run_sync,
        "_skill_path_is_safe": skill_runtime.skill_path_is_safe,
    })

    skill_handler_ctx = env.SkillHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        skills_list_with_cache=env._skills_list_sync_with_cache,
        skills_cache_reset=env._skills_cache_reset,
        skill_install_sync=registry["_skill_install_sync"],
        skill_uninstall_sync=registry["_skill_uninstall_sync"],
        skills_run_sync=lambda *args, **kwargs: registry["_skills_run_sync"](*args, **kwargs),
        skill_path_is_safe=registry["_skill_path_is_safe"],
        audit=env.audit,
        log_info=env.log.info,
    )
    skill_handlers = env.make_skill_handlers(skill_handler_ctx)
    env.export_handler_attrs(registry, skill_handlers, {"handle_v1_skills": "skills", "handle_v1_skills_install": "install", "handle_v1_skills_uninstall": "uninstall", "handle_v1_skills_run": "run", "handle_v1_skills_reload": "reload"})
    registry.update({"_skill_handler_ctx": skill_handler_ctx, "_skill_handlers": skill_handlers})

    def _agentic_app_config() -> dict[str, Any]:
        app_ref = g.get("_app_ref")
        return app_ref.get(APP_CFG, {}) if app_ref else {}

    agentic_runtime_ctx = env.AgenticRuntimeContext(
        build_plan=env.build_plan,
        recall_sync=env._recall_sync,
        common_status=g["common_status"],
        app_config=_agentic_app_config,
        doctor_sync=g["_doctor_sync"],
        sysinfo_sync=g["_sysinfo_sync"],
        tasks_list_sync=registry["_tasks_list_sync"],
        file_watch_list_sync=env._file_watch_list_sync,
        browser_head_sync=env._browser_head_sync,
    )
    agentic_runtime = env.make_agentic_runtime(agentic_runtime_ctx)
    registry.update({
        "_agentic_app_config": _agentic_app_config,
        "_agentic_runtime_ctx": agentic_runtime_ctx,
        "_agentic_runtime": agentic_runtime,
        "_react_sync": agentic_runtime.react_sync,
        "_reflect_sync": agentic_runtime.reflect_sync,
    })

    planner_handler_ctx = env.PlannerHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        build_plan=env.build_plan,
        audit=env.audit,
    )
    planner_handlers = env.make_planner_handlers(planner_handler_ctx)
    env.export_handler_attrs(registry, planner_handlers, {"handle_v1_plan": "plan"})
    registry.update({"_planner_handler_ctx": planner_handler_ctx, "_planner_handlers": planner_handlers})

    agentic_handler_ctx = env.AgenticHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        react_sync=registry["_react_sync"],
        reflect_sync=registry["_reflect_sync"],
        audit=env.audit,
    )
    agentic_handlers = env.make_agentic_handlers(agentic_handler_ctx)
    env.export_handler_attrs(registry, agentic_handlers, {"handle_v1_react": "react", "handle_v1_reflect": "reflect"})
    registry.update({"_agentic_handler_ctx": agentic_handler_ctx, "_agentic_handlers": agentic_handlers})

    file_watch_handler_ctx = env.FileWatchHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        app_cfg_key=APP_CFG,
        home=Path.home(),
        list_sync=env._file_watch_list_sync,
        add_sync=env._file_watch_add_sync,
        remove_sync=env._file_watch_remove_sync,
        utc_now=env.utc_now,
    )
    file_watch_handlers = env.make_file_watch_handlers(file_watch_handler_ctx)
    env.export_handler_attrs(registry, file_watch_handlers, {"handle_v1_watch_files": "watch_files"})
    registry.update({"_file_watch_handler_ctx": file_watch_handler_ctx, "_file_watch_handlers": file_watch_handlers})

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

    rr = env._resource_runtime
    registry.update({
        "_hooks_list_sync": rr.hooks_list_sync, "_agents_list_sync": rr.agents_list_sync,
        "_subagents_list_sync": rr.subagents_list_sync, "_subagents_spawn_sync": rr.subagents_spawn_sync,
        "_mission_show_sync": rr.mission_show_sync, "_mission_templates_sync": rr.mission_templates_sync,
        "_mission_compose_sync": rr.mission_compose_sync, "_mission_propose_sync": _mission_propose_sync,
        "_mission_create_sync": rr.mission_create_sync, "_mission_run_sync": rr.mission_run_sync,
    })
    resource_handler_ctx = env.ResourceHandlerContext(
        require_auth=env.require_auth, record_request=env._record_request, cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR, list_missions_sync=env._list_missions_sync, list_reports_sync=env._list_reports_sync,
        hooks_list_sync=registry["_hooks_list_sync"], agents_list_sync=registry["_agents_list_sync"],
        subagents_list_sync=registry["_subagents_list_sync"], mission_show_sync=registry["_mission_show_sync"],
        mission_templates_sync=registry["_mission_templates_sync"], mission_compose_sync=registry["_mission_compose_sync"],
        mission_propose_sync=registry["_mission_propose_sync"], mission_create_sync=registry["_mission_create_sync"],
        mission_run_sync=registry["_mission_run_sync"], subagent_spawn_sync=registry["_subagents_spawn_sync"], audit=env.audit,
    )
    resource_handlers = env.make_resource_handlers(resource_handler_ctx)
    env.export_handler_attrs(registry, resource_handlers, {"handle_v1_missions": "missions", "handle_v1_reports": "reports", "handle_v1_hooks": "hooks", "handle_v1_agents": "agents", "handle_v1_subagents": "subagents", "handle_v1_subagents_spawn": "subagents_spawn", "handle_v1_mission_show": "mission_show", "handle_v1_mission_templates": "mission_templates", "handle_v1_mission_compose": "mission_compose", "handle_v1_mission_propose": "mission_propose", "handle_v1_mission_create": "mission_create", "handle_v1_mission_run": "mission_run"})
    registry.update({"_resource_handler_ctx": resource_handler_ctx, "_resource_handlers": resource_handlers})
    return registry

__all__ = ["build_tasks_skills_resources_registries"]

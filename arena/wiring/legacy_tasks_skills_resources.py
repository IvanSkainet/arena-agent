"""Legacy task, skill and resource handler/runtime wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Callable

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

    registry.update({
        "_hooks_list_sync": env._resource_runtime.hooks_list_sync,
        "_agents_list_sync": env._resource_runtime.agents_list_sync,
        "_subagents_list_sync": env._resource_runtime.subagents_list_sync,
        "_subagents_spawn_sync": env._resource_runtime.subagents_spawn_sync,
        "_mission_show_sync": env._resource_runtime.mission_show_sync,
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
        subagent_spawn_sync=registry["_subagents_spawn_sync"],
        audit=env.audit,
    )
    resource_handlers = env.make_resource_handlers(resource_handler_ctx)
    env.export_handler_attrs(registry, resource_handlers, {"handle_v1_missions": "missions", "handle_v1_reports": "reports", "handle_v1_hooks": "hooks", "handle_v1_agents": "agents", "handle_v1_subagents": "subagents", "handle_v1_subagents_spawn": "subagents_spawn", "handle_v1_mission_show": "mission_show"})
    registry.update({"_resource_handler_ctx": resource_handler_ctx, "_resource_handlers": resource_handlers})
    return registry


__all__ = ["build_tasks_skills_resources_registries"]

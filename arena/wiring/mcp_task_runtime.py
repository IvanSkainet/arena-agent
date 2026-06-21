"""MCP tool runtime and task-runner wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from arena.wiring.env import RuntimeEnv


def build_mcp_task_runtimes(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build MCP tool runtime and task-runner compatibility globals."""
    env = RuntimeEnv(g)
    registry: dict[str, Any] = {}

    def _cleanup_mcp_sessions() -> int:
        return env._mcp_cleanup_sessions(env.MCP_SESSIONS)

    def _mcp_app_config() -> dict:
        app_ref = g.get("_app_ref")
        return app_ref.get("cfg", {}) if app_ref else {}

    file_watch_ctx = env.FileWatchRuntimeContext(
        home=Path.home(),
        default_root=Path.home(),
        emit_event=env.emit_event,
        utc_now=env.utc_now,
        log_info=env.log.info,
        log_warning=env.log.warning,
    )
    file_watch_runtime = env.make_file_watch_runtime(file_watch_ctx)
    registry.update({
        "_file_watch_ctx": file_watch_ctx,
        "_file_watch_runtime": file_watch_runtime,
        "_file_watch_list_sync": file_watch_runtime.list_sync,
        "_file_watch_add_sync": file_watch_runtime.add_sync,
        "_file_watch_remove_sync": file_watch_runtime.remove_sync,
        "file_watch_loop": file_watch_runtime.loop,
    })

    mcp_tool_ctx = env.McpToolContext(
        version=env.VERSION,
        bin_dir=env.BIN,
        bridge_dir=env.BRIDGE_DIR,
        reports_dir=env.REPORTS_DIR,
        subprocess_kwargs=env._subprocess_kwargs,
        blocked_reason=env.blocked_reason,
        first_word=env.first_word,
        cautious_allow=env.CAUTIOUS_ALLOW,
        under_root=env.under_root,
        write_fact=lambda entry: g["_write_fact"](entry),
        load_facts=lambda *args, **kwargs: g["_load_facts"](*args, **kwargs),
        recall_sync=lambda *args, **kwargs: g["_recall_sync"](*args, **kwargs),
        recall_digest_sync=lambda *args, **kwargs: g["_recall_digest_sync"](*args, **kwargs),
        audit=env.audit,
        app_config=_mcp_app_config,
        common_status=lambda cfg: g["common_status"](cfg),
        build_plan=env.build_plan,
        file_watch_list_sync=registry["_file_watch_list_sync"],
        file_watch_add_sync=registry["_file_watch_add_sync"],
        file_watch_remove_sync=registry["_file_watch_remove_sync"],
        react_sync=lambda *args, **kwargs: g["_react_sync"](*args, **kwargs),
        reflect_sync=lambda *args, **kwargs: g["_reflect_sync"](*args, **kwargs),
        utc_now=env.utc_now,
        skills_list_sync_with_cache=env._skills_list_sync_with_cache,
        skills_run_sync=lambda *args, **kwargs: g["_skills_run_sync"](*args, **kwargs),
    )
    mcp_tool_runtime = env.make_mcp_tool_runtime(mcp_tool_ctx)
    registry.update({
        "_cleanup_mcp_sessions": _cleanup_mcp_sessions,
        "_mcp_app_config": _mcp_app_config,
        "_mcp_tool_ctx": mcp_tool_ctx,
        "_mcp_tool_runtime": mcp_tool_runtime,
        "MCP_TOOLS": mcp_tool_runtime.tools,
        "run_local": mcp_tool_runtime.run_local,
        "run_sd": mcp_tool_runtime.run_sd,
        "text_content": mcp_tool_runtime.text_content,
        "call_tool": mcp_tool_runtime.call_tool,
        "handle_rpc": mcp_tool_runtime.handle_rpc,
    })

    task_runner_ctx = env.TaskRunnerContext(
        inbox=env.INBOX,
        running=env.RUNNING,
        done=env.DONE,
        failed=env.FAILED,
        blocked_reason=env.blocked_reason,
        cleanup_mcp_sessions=_cleanup_mcp_sessions,
        utc_now=env.utc_now,
        log_info=env.log.info,
        log_error=env.log.error,
    )
    task_runner_runtime = env.make_task_runner_runtime(task_runner_ctx)
    registry.update({
        "_task_runner_ctx": task_runner_ctx,
        "_task_runner_runtime": task_runner_runtime,
        "move_atomic": task_runner_runtime.move_atomic,
        "task_ensure_dirs": task_runner_runtime.ensure_dirs,
        "task_run_one": task_runner_runtime.run_one,
        "task_runner_loop": task_runner_runtime.runner_loop,
    })
    return registry


__all__ = ["build_mcp_task_runtimes"]

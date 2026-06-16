"""Legacy MCP tool runtime and task-runner wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


def build_mcp_task_runtimes(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build MCP tool runtime and task-runner compatibility globals."""
    globals().update(g)
    registry: dict[str, Any] = {}

    def _cleanup_mcp_sessions() -> int:
        return _mcp_cleanup_sessions(MCP_SESSIONS)

    def _mcp_app_config() -> dict:
        app_ref = g.get("_app_ref")
        return app_ref.get("cfg", {}) if app_ref else {}

    mcp_tool_ctx = McpToolContext(
        version=VERSION,
        bin_dir=BIN,
        bridge_dir=BRIDGE_DIR,
        reports_dir=REPORTS_DIR,
        subprocess_kwargs=_subprocess_kwargs,
        blocked_reason=blocked_reason,
        first_word=first_word,
        cautious_allow=CAUTIOUS_ALLOW,
        under_root=under_root,
        write_fact=lambda entry: g["_write_fact"](entry),
        load_facts=lambda: g["_load_facts"](),
        audit=audit,
        app_config=_mcp_app_config,
        common_status=lambda cfg: g["common_status"](cfg),
        skills_list_sync_with_cache=_skills_list_sync_with_cache,
        skills_run_sync=lambda *args, **kwargs: g["_skills_run_sync"](*args, **kwargs),
    )
    mcp_tool_runtime = make_mcp_tool_runtime(mcp_tool_ctx)
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

    task_runner_ctx = TaskRunnerContext(
        inbox=INBOX,
        running=RUNNING,
        done=DONE,
        failed=FAILED,
        blocked_reason=blocked_reason,
        cleanup_mcp_sessions=_cleanup_mcp_sessions,
        utc_now=utc_now,
        log_info=log.info,
        log_error=log.error,
    )
    task_runner_runtime = make_task_runner_runtime(task_runner_ctx)
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

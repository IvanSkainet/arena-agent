"""MCP tool registry and JSON-RPC dispatcher."""
from __future__ import annotations

import json
import types as _types
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from arena.mcp.tool_registry import MCP_TOOLS
from arena.mcp.tool_utils import make_run_local, make_run_sd, text_content
from arena.mcp.tool_browser import handle_browser_tool
from arena.mcp.tool_exec import handle_exec_tool
from arena.mcp.tool_fs import handle_fs_tool
from arena.mcp.tool_fs_search import handle_fs_search_tool
from arena.mcp.tool_fs_tree_diff import handle_fs_tree_diff_tool
from arena.mcp.tool_memory_export_import import handle_memory_export_import_tool
from arena.mcp.tool_git import handle_git_tool
from arena.mcp.tool_memory import handle_memory_tool
from arena.mcp.tool_misc import handle_misc_tool
from arena.mcp.tool_watch import handle_watch_tool
from arena.mcp.tool_agentic import handle_agentic_tool
from arena.mcp.tool_desktop import handle_desktop_tool
from arena.mcp.tool_mobile import handle_mobile_tool
from arena.mcp.tool_asr import handle_asr_tool
from arena.mcp.tool_net import handle_net_tool
from arena.mcp.tool_mission import handle_mission_tool
from arena.mcp.tool_scenarios import handle_scenario_tool
from arena.mcp.tool_plan import handle_plan_tool



@dataclass(frozen=True)
class McpToolContext:
    version: str
    bin_dir: Any
    bridge_dir: Any
    reports_dir: Any
    subprocess_kwargs: Callable[[], dict[str, Any]]
    blocked_reason: Callable[[str], str | None]
    first_word: Callable[[str], str]
    cautious_allow: set[str]
    under_root: Callable[[Path, Path], bool]
    write_fact: Callable[[dict[str, Any]], None]
    load_facts: Callable[..., list[dict[str, Any]]]
    recall_sync: Callable[..., dict[str, Any]]
    recall_digest_sync: Callable[..., dict[str, Any]]
    audit: Callable[[dict[str, Any]], None]
    app_config: Callable[[], dict[str, Any]]
    common_status: Callable[[dict[str, Any]], dict[str, Any]]
    build_plan: Callable[..., dict[str, Any]]
    file_watch_list_sync: Callable[[], dict[str, Any]]
    file_watch_add_sync: Callable[..., dict[str, Any]]
    file_watch_remove_sync: Callable[[str], dict[str, Any]]
    react_sync: Callable[..., dict[str, Any]]
    reflect_sync: Callable[..., dict[str, Any]]
    utc_now: Callable[[], str]
    skills_list_sync_with_cache: Callable[[], dict[str, Any]]
    skills_run_sync: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class McpToolRuntime:
    tools: list[dict[str, Any]]
    run_local: Callable[..., tuple[int, str, str]]
    run_sd: Callable[..., tuple[int, str, str]]
    text_content: Callable[[str], dict[str, Any]]
    call_tool: Callable[[str, dict[str, Any]], dict[str, Any]]
    handle_rpc: Callable[[dict[str, Any]], dict[str, Any] | None]


def make_mcp_tool_runtime(ctx: McpToolContext) -> McpToolRuntime:
    run_local = make_run_local(ctx.subprocess_kwargs)
    run_sd = make_run_sd(bin_dir=ctx.bin_dir, subprocess_kwargs=ctx.subprocess_kwargs)
    # Preserve historical module names for compatibility diagnostics/tests.
    try:
        run_local.__module__ = __name__
        run_sd.__module__ = __name__
        text_content.__module__ = __name__
    except Exception:
        pass


    def call_tool(name: str, args: dict) -> dict:
        """MCP tool dispatcher."""
        try:
            for handler in (
                lambda: handle_exec_tool(name, args, ctx=ctx, run_sd=run_sd),
                lambda: handle_fs_tool(name, args, ctx=ctx),
                lambda: handle_fs_search_tool(name, args, ctx=ctx),
                lambda: handle_fs_tree_diff_tool(name, args, ctx=ctx),
                lambda: handle_memory_export_import_tool(name, args, ctx=ctx),
                lambda: handle_git_tool(name, args, ctx=ctx),
                lambda: handle_browser_tool(name, args, ctx=ctx, run_local=run_local, run_sd=run_sd),
                lambda: handle_memory_tool(name, args, ctx=ctx, run_local=run_local),
                lambda: handle_plan_tool(name, args, ctx=ctx),
                lambda: handle_watch_tool(name, args, ctx=ctx),
                lambda: handle_agentic_tool(name, args, ctx=ctx),
                lambda: handle_desktop_tool(name, args, ctx=ctx),
                lambda: handle_mobile_tool(name, args, ctx=ctx),
                lambda: handle_net_tool(name, args, ctx=ctx, run_sd=run_sd),
                lambda: handle_asr_tool(name, args, ctx=ctx),
                lambda: handle_mission_tool(name, args, ctx=ctx),
                # v4.54.0: scenario orchestration. The scenarios
                # runtime needs to invoke OTHER tools (including
                # other scenarios) from within a step, so we pass
                # a proxy ctx that carries the same call_tool
                # closure we're building here. types.SimpleNamespace
                # keeps the frozen-dataclass ctx immutable.
                lambda: handle_scenario_tool(name, args, ctx=_types.SimpleNamespace(call_tool=call_tool)),
                lambda: handle_misc_tool(name, args, ctx=ctx, run_local=run_local),
            ):
                result = handler()
                if result is not None:
                    return result
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {type(e).__name__}: {e}"}]}
        return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}


    def handle_rpc(msg: dict) -> dict | None:
        """JSON-RPC 2.0 handler for MCP."""
        m = msg.get("method", "")
        rid = msg.get("id")
        if m == "initialize":
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "arena-unified-bridge", "version": ctx.version},
                "capabilities": {"tools": {"listChanged": False}}}}
        if m == "tools/list":
            return {"jsonrpc": "2.0", "id": rid, "result": {"tools": MCP_TOOLS}}
        if m == "tools/call":
            params = msg.get("params") or {}
            return {"jsonrpc": "2.0", "id": rid, "result": call_tool(params.get("name", ""), params.get("arguments") or {})}
        if m == "notifications/initialized":
            return None
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Method not found: {m}"}}

    return McpToolRuntime(
        tools=MCP_TOOLS,
        run_local=run_local,
        run_sd=run_sd,
        text_content=text_content,
        call_tool=call_tool,
        handle_rpc=handle_rpc,
    )

"""MCP tool registry and JSON-RPC dispatcher."""
from __future__ import annotations

import json
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

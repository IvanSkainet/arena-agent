"""MCP tool registry and JSON-RPC dispatcher."""
from __future__ import annotations

import json
import types as _types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.control import _agent_halt_block_for_tool
from arena.mcp.custom_tools import handle_custom_tool, tool_defs as custom_tool_defs
from arena.mcp.tool_agentic import handle_agentic_tool
from arena.mcp.tool_asr import handle_asr_tool
from arena.mcp.tool_audit import handle_audit_tool
from arena.mcp.tool_browser import handle_browser_tool
from arena.mcp.tool_browser_headed import handle_browser_headed_tool
from arena.mcp.tool_capability_gap import handle_capability_gap_tool
from arena.mcp.tool_code import handle_code_tool
from arena.mcp.tool_code_artifact import handle_code_artifact_tool
from arena.mcp.tool_code_matrix import handle_code_matrix_tool
from arena.mcp.tool_code_project import handle_code_project_tool
from arena.mcp.tool_code_session import handle_code_session_tool
from arena.mcp.tool_desktop import handle_desktop_tool
from arena.mcp.tool_desktop_app import handle_desktop_app_tool
from arena.mcp.tool_desktop_input import handle_desktop_input_tool
from arena.mcp.tool_document import handle_document_tool
from arena.mcp.tool_emulator import handle_emulator_tool
from arena.mcp.tool_exec import handle_exec_tool
from arena.mcp.tool_foundry import handle_foundry_tool
from arena.mcp.tool_fs import handle_fs_tool
from arena.mcp.tool_fs_search import handle_fs_search_tool
from arena.mcp.tool_fs_tree_diff import handle_fs_tree_diff_tool
from arena.mcp.tool_git import handle_git_tool
from arena.mcp.tool_image import handle_image_tool
from arena.mcp.tool_input_helper import handle_input_helper_tool
from arena.mcp.tool_mcp_ext import handle_mcp_ext_tool
from arena.mcp.tool_mcp_server_foundry import handle_mcp_server_foundry_tool
from arena.mcp.tool_memory import handle_memory_tool
from arena.mcp.tool_memory_export_import import handle_memory_export_import_tool
from arena.mcp.tool_misc import handle_misc_tool
from arena.mcp.tool_mission import handle_mission_tool
from arena.mcp.tool_mobile import handle_mobile_tool
from arena.mcp.tool_mobile_ext import handle_mobile_ext_tool
from arena.mcp.tool_net import handle_net_tool
from arena.mcp.tool_ocr import handle_ocr_tool
from arena.mcp.tool_plan import handle_plan_tool
from arena.mcp.tool_registry import MCP_TOOLS
from arena.mcp.tool_runtime import handle_runtime_tool
from arena.mcp.tool_scenarios import handle_scenario_tool
from arena.mcp.tool_service import handle_service_tool
from arena.mcp.tool_ship import handle_ship_tool
from arena.mcp.tool_utils import make_run_local, make_run_sd, text_content
from arena.mcp.tool_watch import handle_watch_tool
from arena.mcp.tool_workbench import handle_workbench_tool


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
    play_beep_sync: Callable[[str, int, int], dict[str, Any]]
    send_notification_sync: Callable[[str, str], dict[str, Any]]
    play_beep_sync: Callable[[str, int, int], dict[str, Any]]
    send_notification_sync: Callable[[str, str], dict[str, Any]]


@dataclass(frozen=True)
class McpToolRuntime:
    tools: list[dict[str, Any]]
    run_local: Callable[..., tuple[int, str, str]]
    run_sd: Callable[..., tuple[int, str, str]]
    text_content: Callable[[str], dict[str, Any]]
    call_tool: Callable[[str, dict[str, Any]], dict[str, Any]]
    handle_rpc: Callable[[dict[str, Any]], dict[str, Any] | None]


# One concept, one meaning -- whatever the handler happens to call it.
#
# The self-extension chain was broken by nothing more than vocabulary:
# ``code_project.*`` identifies a project as ``name`` (7 tools), while
# ``tool_foundry.validate/publish`` call the same project ``project``. An
# agent that had just created a project with ``name`` got
# "project name must use only letters..." from ``write`` when it reasonably
# said ``project`` -- a validation error about an argument it never sent.
# Measured across the surface: five namespaces carried the same kind of
# split (code_project/code_run/code_session name|project,
# capability_gap id|gap_id, mission q|query).
#
# Fixed once here rather than in nineteen handlers, because the next tool
# added would reintroduce it. Each group is a set of names meaning the same
# thing; on the way in, whichever the caller used is copied to the others so
# every handler finds the key it expects. Never overwrites a value the
# caller actually supplied.
_ARG_SYNONYMS: tuple[frozenset[str], ...] = (
    frozenset({"name", "project"}),
    frozenset({"id", "gap_id"}),
    frozenset({"q", "query"}),
)


def _accept_synonyms(tool: str, args: dict) -> dict:
    """Let a caller name an argument any of the ways the surface names it."""
    if not isinstance(args, dict) or not args:
        return args
    ns = tool.split(".", 1)[0]
    # Only for namespaces that actually disagree with themselves; elsewhere a
    # "name" and a "project" could legitimately be two different things.
    if ns not in {"code_project", "code_run", "code_session",
                  "tool_foundry", "capability_gap", "mission"}:
        return args
    out = dict(args)
    for group in _ARG_SYNONYMS:
        supplied = [k for k in group if out.get(k) not in (None, "")]
        if len(supplied) != 1:
            continue  # nothing given, or the caller was explicit about both
        value = out[supplied[0]]
        for key in group:
            if out.get(key) in (None, ""):
                out[key] = value
    return out


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
            args = _accept_synonyms(name, args)
            # v4.97.0: full agent stop (kill-switch). Read-only tools still
            # run; everything mutating is blocked while halted. This is the
            # authoritative gate for the agent, because every agent action --
            # MCP tools/call AND /v1/extension/execute -- funnels through here.
            _halt_block = _agent_halt_block_for_tool(name)
            if _halt_block is not None:
                return {"isError": True,
                        "content": [{"type": "text",
                                     "text": json.dumps(_halt_block,
                                                        ensure_ascii=False)}]}
            for handler in (
                # v4.96.0: agent-authored custom tools (self-extending
                # environment). Resolved first; recursion goes back through
                # this same call_tool (via the ctx, like scenarios) so the
                # wrapped built-in call keeps its own policy/risk handling.
                lambda: handle_custom_tool(name, args, ctx=_types.SimpleNamespace(call_tool=call_tool)),
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
                lambda: handle_desktop_input_tool(name, args, ctx=ctx),
                lambda: handle_desktop_app_tool(name, args, ctx=ctx),
                lambda: handle_desktop_tool(name, args, ctx=ctx),
                lambda: handle_mobile_ext_tool(name, args, ctx=ctx),
                lambda: handle_mobile_tool(name, args, ctx=ctx),
                lambda: handle_emulator_tool(name, args, ctx=ctx),
                lambda: handle_capability_gap_tool(name, args, ctx=ctx),
                lambda: handle_net_tool(name, args, ctx=ctx, run_sd=run_sd),
                lambda: handle_asr_tool(name, args, ctx=ctx),
                lambda: handle_ocr_tool(name, args, ctx=ctx),
                lambda: handle_document_tool(name, args, ctx=ctx),
                lambda: handle_image_tool(name, args, ctx=ctx),
                lambda: handle_mcp_ext_tool(name, args, ctx=ctx),
                lambda: handle_code_tool(name, args, ctx=ctx),
                lambda: handle_runtime_tool(name, args, ctx=ctx),
                lambda: handle_code_project_tool(name, args, ctx=ctx),
                lambda: handle_code_artifact_tool(name, args, ctx=ctx),
                lambda: handle_code_matrix_tool(name, args, ctx=ctx),
                lambda: handle_code_session_tool(name, args, ctx=ctx),
                lambda: handle_workbench_tool(name, args, ctx=ctx),
                lambda: handle_mcp_server_foundry_tool(name, args, ctx=ctx),
                lambda: handle_ship_tool(name, args, ctx=ctx),
                lambda: handle_service_tool(name, args, ctx=ctx),
                lambda: handle_foundry_tool(name, args, ctx=ctx),
                lambda: handle_browser_headed_tool(name, args, ctx=ctx),
                lambda: handle_mission_tool(name, args, ctx=ctx),
                # v4.54.0: scenario orchestration. The scenarios
                # runtime needs to invoke OTHER tools (including
                # other scenarios) from within a step, so we pass
                # a proxy ctx that carries the same call_tool
                # closure we're building here. types.SimpleNamespace
                # keeps the frozen-dataclass ctx immutable.
                lambda: handle_scenario_tool(name, args, ctx=_types.SimpleNamespace(call_tool=call_tool)),
                lambda: handle_audit_tool(name, args, ctx=ctx),
                lambda: handle_input_helper_tool(name, args, ctx=ctx),
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
            # Preserve the MCP_TOOLS object identity when there are no
            # agent-authored tools (the contract test asserts `is MCP_TOOLS`);
            # append the dynamic authored tools only when some exist.
            extra = custom_tool_defs()
            tools = MCP_TOOLS if not extra else MCP_TOOLS + extra
            return {"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}}
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

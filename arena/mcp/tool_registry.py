"""MCP tool metadata registry."""
from __future__ import annotations
from arena.mcp.tool_registry_mission import MISSION_MCP_TOOLS
from arena.mcp.tool_registry_mobile import MOBILE_MCP_TOOLS
from arena.mcp.tool_desktop_input import DESKTOP_INPUT_MCP_TOOLS
from arena.mcp.tool_mobile_ext import MOBILE_EXT_MCP_TOOLS
from arena.mcp.tool_browser_headed import BROWSER_HEADED_MCP_TOOLS
from arena.mcp.tool_registry_asr import ASR_MCP_TOOLS
from arena.mcp.tool_registry_net import NET_MCP_TOOLS
from arena.mcp.tool_registry_scenarios import SCENARIO_MCP_TOOLS
MCP_TOOLS = [
    {"name": "ping", "description": "Return pong (liveness)",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "echo", "description": "Echo arguments back",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}},
    {"name": "exec", "description": "Run shell command outside bridge cgroup (via sd-exec)",
     "inputSchema": {"type": "object", "properties": {
         "cmd": {"type": "string"}, "timeout": {"type": "integer", "default": 60}},
         "required": ["cmd"], "additionalProperties": False}},
    # v4.67.0: namespaced versions of the four legacy bare-name
    # tools. The bare names are kept in MCP_TOOLS for backward
    # compat with chat-extension adapters that haven't been
    # updated yet, but new code should call the ``exec.*`` form.
    # The test ``tests/test_mcp_input_schema_validation.py``
    # still whitelists the bare names (see the LEGACY_BARE_NAMES
    # set in ``scripts/catalogue_harden.py``) so the namespace-
    # convention guard doesn't fail on the pre-existing entries.
    # The dispatch in ``arena.mcp.tool_exec`` /
    # ``arena.mcp.tool_misc`` accepts both forms.
    {"name": "exec.ping", "description": "Namespaced alias for ``ping``. Return pong (liveness).",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "exec.echo", "description": "Namespaced alias for ``echo``. Echo arguments back.",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}},
    {"name": "exec.exec", "description": "Namespaced alias for ``exec``. Run shell command outside bridge cgroup (via sd-exec).",
     "inputSchema": {"type": "object", "properties": {
         "cmd": {"type": "string"}, "timeout": {"type": "integer", "default": 60}},
         "required": ["cmd"], "additionalProperties": False}},
    {"name": "fs.read", "description": "Read file contents (utf-8)",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "max_bytes": {"type": "integer", "default": 200000}},
         "required": ["path"], "additionalProperties": False}},
    {"name": "fs.write", "description": "Write file (utf-8). Creates directories.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}},
    {"name": "fs.list", "description": "List directory entries",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    {"name": "fs.edit", "description": "Find-and-replace in a text file (str_replace_editor semantics). old_text must be unique unless replace_all=true. Set preview=true for a safe preview/confirm workflow.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}, "replace_all": {"type": "boolean", "default": False}, "preview": {"type": "boolean", "default": False}}, "required": ["path", "old_text", "new_text"], "additionalProperties": False}},
    {"name": "fs.edit_apply", "description": "Apply a previously created fs.edit preview by preview_id.",
     "inputSchema": {"type": "object", "properties": {"preview_id": {"type": "string"}}, "required": ["preview_id"], "additionalProperties": False}},
    {"name": "fs.edit_rollback", "description": "Rollback a previously applied safe edit by rollback_id.",
     "inputSchema": {"type": "object", "properties": {"rollback_id": {"type": "string"}, "force": {"type": "boolean", "default": False}}, "required": ["rollback_id"], "additionalProperties": False}},
    {"name": "fs.view", "description": "View file contents with line numbers. Optional view_range=[start,end] for line range (1-indexed).",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"},
         "view_range": {"type": "array", "items": {"type": "integer"}, "maxItems": 2}},
         "required": ["path"], "additionalProperties": False}},
    {"name": "fs.create", "description": "Create a new text file. Fails if file already exists (use fs.edit to modify).",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"},
         "content": {"type": "string"}},
         "required": ["path", "content"], "additionalProperties": False}},
    {"name": "fs.search", "description": "Search file contents by regex pattern. Returns matches with file path, line number, and line content.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Directory or file to search in"},
         "pattern": {"type": "string", "description": "Regex pattern to search for"},
         "glob": {"type": "string", "description": "Optional file glob filter (e.g. *.py)"},
         "max_results": {"type": "integer", "default": 50},
         "context": {"type": "integer", "default": 0, "description": "Lines of context around each match"},
         "ignore_case": {"type": "boolean", "default": False}},
         "required": ["path", "pattern"], "additionalProperties": False}},
    {"name": "fs.grep", "description": "Alias for fs.search. Search file contents by regex pattern.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"},
         "pattern": {"type": "string"},
         "glob": {"type": "string"},
         "max_results": {"type": "integer", "default": 50},
         "context": {"type": "integer", "default": 0},
         "ignore_case": {"type": "boolean", "default": False}},
         "required": ["path", "pattern"], "additionalProperties": False}},
    {"name": "fs.tree", "description": "Show directory tree structure. Optional max_depth and glob filter.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Directory to show tree for"},
         "max_depth": {"type": "integer", "default": 3, "description": "Maximum depth (1-10)"},
         "show_files": {"type": "boolean", "default": True},
         "glob": {"type": "string", "description": "Optional file glob filter (e.g. *.py)"}},
         "required": ["path"], "additionalProperties": False}},
    {"name": "fs.diff", "description": "Compare two text files and return unified diff.",
     "inputSchema": {"type": "object", "properties": {
         "path_a": {"type": "string", "description": "First file (old)"},
         "path_b": {"type": "string", "description": "Second file (new)"}},
         "required": ["path_a", "path_b"], "additionalProperties": False}},
    {"name": "browser.search", "description": "DuckDuckGo search via pure-Python (no chromium)",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "n": {"type": "integer", "default": 5}},
         "required": ["query"], "additionalProperties": False}},
    {"name": "browser.read", "description": "Readability-extract clean text from URL",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"], "additionalProperties": False}},
    {"name": "browser.shot", "description": "Take headless chromium screenshot via sd-exec",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"], "additionalProperties": False}},
    {"name": "desktop.displays", "description": "List desktop displays/outputs with global geometry for multi-monitor aware automation.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "desktop.windows", "description": "List desktop windows, with optional title/class/pid/display filters and display annotations.",
     "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "class": {"type": "string"}, "desktop_file": {"type": "string"}, "resource_name": {"type": "string"}, "pid": {"type": "integer"}, "display": {"type": "string"}, "active_only": {"type": "boolean", "default": False}, "include_displays": {"type": "boolean", "default": False}}, "additionalProperties": False}},
    {"name": "desktop.focus", "description": "Focus a desktop window by id, semantic filters, or OCR text query. Supports dry-run resolution before actual focusing.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "query": {"type": "string"}, "title": {"type": "string"}, "class": {"type": "string"}, "desktop_file": {"type": "string"}, "resource_name": {"type": "string"}, "pid": {"type": "integer"}, "display": {"type": "string"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": True}, "within_active_window": {"type": "boolean", "default": False}, "crop_active_window": {"type": "boolean", "default": True}, "verify": {"type": "boolean", "default": True}, "timeout_ms": {"type": "integer", "default": 1500}, "dry_run": {"type": "boolean", "default": False}}, "additionalProperties": False}},
    {"name": "desktop.window_action", "description": "Manipulate a desktop window: move, resize, minimize, maximize, restore, close, center, snap it into common tiling positions, move it to another display, or toggle fullscreen, with optional dry-run target resolution.",
     "inputSchema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["minimize", "restore", "maximize", "unmaximize", "fullscreen", "unfullscreen", "close", "center", "move_to_display", "snap_left", "snap_right", "snap_top", "snap_bottom", "snap_top_left", "snap_top_right", "snap_bottom_left", "snap_bottom_right", "move", "resize", "move_resize"]}, "id": {"type": "string"}, "query": {"type": "string"}, "title": {"type": "string"}, "class": {"type": "string"}, "desktop_file": {"type": "string"}, "resource_name": {"type": "string"}, "pid": {"type": "integer"}, "display": {"type": "string"}, "target_display": {"type": "string"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": True}, "within_active_window": {"type": "boolean", "default": False}, "crop_active_window": {"type": "boolean", "default": True}, "x": {"type": "integer"}, "y": {"type": "integer"}, "width": {"type": "integer"}, "height": {"type": "integer"}, "verify": {"type": "boolean", "default": True}, "timeout_ms": {"type": "integer", "default": 1000}, "dry_run": {"type": "boolean", "default": False}}, "required": ["action"], "additionalProperties": False}},
    {"name": "desktop.resolve_text_target", "description": "Resolve OCR text on the desktop into a containing window target, with display-aware and active-window-aware ranking.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "display": {"type": "string"}, "title": {"type": "string"}, "class": {"type": "string"}, "desktop_file": {"type": "string"}, "resource_name": {"type": "string"}, "pid": {"type": "integer"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": True}, "within_active_window": {"type": "boolean", "default": False}, "crop_active_window": {"type": "boolean", "default": True}}, "required": ["query"], "additionalProperties": False}},
    {"name": "desktop.text_action", "description": "Resolve visible text into a target window or click point and then run a high-level desktop action such as resolve, focus, click, center, snap, or window move/resize.",
     "inputSchema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["resolve", "focus", "click", "center", "move_to_display", "snap_left", "snap_right", "snap_top", "snap_bottom", "snap_top_left", "snap_top_right", "snap_bottom_left", "snap_bottom_right", "minimize", "restore", "maximize", "unmaximize", "fullscreen", "unfullscreen", "close", "move", "resize", "move_resize"], "default": "resolve"}, "query": {"type": "string"}, "display": {"type": "string"}, "target_display": {"type": "string"}, "title": {"type": "string"}, "class": {"type": "string"}, "desktop_file": {"type": "string"}, "resource_name": {"type": "string"}, "pid": {"type": "integer"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": True}, "within_active_window": {"type": "boolean", "default": False}, "crop_active_window": {"type": "boolean", "default": True}, "target_position": {"type": "string", "enum": ["center", "left", "right", "top", "bottom"], "default": "center"}, "offset_x": {"type": "integer", "default": 0}, "offset_y": {"type": "integer", "default": 0}, "button": {"type": "string", "default": "left"}, "double": {"type": "boolean", "default": False}, "activate": {"type": "boolean", "default": True}, "verify": {"type": "boolean", "default": True}, "timeout_ms": {"type": "integer", "default": 1000}, "dry_run": {"type": "boolean", "default": False}}, "required": ["query"], "additionalProperties": False}},
    {"name": "desktop.ocr", "description": "Run OCR on a fresh desktop screenshot and return recognized text with bounding boxes.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "display": {"type": "string"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": False}, "within_active_window": {"type": "boolean", "default": False}}, "additionalProperties": False}},
    {"name": "desktop.find_text", "description": "Find text on the current desktop and return the best matching bounding boxes and click coordinates.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "display": {"type": "string"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": False}, "within_active_window": {"type": "boolean", "default": False}}, "required": ["query"], "additionalProperties": False}},
    {"name": "desktop.click_text", "description": "Find text on the desktop, rank the best match, and click it in one step.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "display": {"type": "string"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": True}, "within_active_window": {"type": "boolean", "default": False}, "target_position": {"type": "string", "enum": ["center", "left", "right", "top", "bottom"], "default": "center"}, "offset_x": {"type": "integer", "default": 0}, "offset_y": {"type": "integer", "default": 0}, "button": {"type": "string", "default": "left"}, "double": {"type": "boolean", "default": False}, "activate": {"type": "boolean", "default": True}, "dry_run": {"type": "boolean", "default": False}}, "required": ["query"], "additionalProperties": False}},
    *MISSION_MCP_TOOLS,
    *SCENARIO_MCP_TOOLS,
    {"name": "plan.create", "description": "Create a structured execution plan for a goal, with suggested tools, steps, risks, and a suggested memory profile.",
     "inputSchema": {"type": "object", "properties": {
         "goal": {"type": "string"},
         "context": {"type": "string"},
         "constraints": {"type": "array", "items": {"type": "string"}},
         "max_steps": {"type": "integer", "default": 8},
         "memory_profile": {"type": "string"}},
         "required": ["goal"], "additionalProperties": False}},
    {"name": "react.run", "description": "Run a bounded reason-act-observe loop using safe observation steps derived from the planner.",
     "inputSchema": {"type": "object", "properties": {
         "goal": {"type": "string"},
         "context": {"type": "string"},
         "constraints": {"type": "array", "items": {"type": "string"}},
         "max_iterations": {"type": "integer", "default": 4},
         "memory_profile": {"type": "string"},
         "url": {"type": "string"}},
         "required": ["goal"], "additionalProperties": False}},
    {"name": "reflect.run", "description": "Reflect on a prior react/planning run and produce concerns, missing evidence, and next steps.",
     "inputSchema": {"type": "object", "properties": {
         "goal": {"type": "string"},
         "run": {"type": "object"},
         "notes": {"type": "string"},
         "outcome": {"type": "string"}}, "additionalProperties": False}},
    {"name": "watch.files", "description": "List, add, or remove file watchers that emit realtime file change events over /v1/events.",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["list", "add", "remove"], "default": "list"},
         "id": {"type": "string"},
         "path": {"type": "string"},
         "recursive": {"type": "boolean", "default": True},
         "patterns": {"type": "array", "items": {"type": "string"}},
         "label": {"type": "string"}}, "additionalProperties": False}},
    {"name": "mem.set", "description": "Remember a fact in a memory profile",
     "inputSchema": {"type": "object", "properties": {
         "profile": {"type": "string", "description": "Memory profile id (default: default)"},
         "key": {"type": "string"}, "value": {"type": "string"},
         "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["key", "value"], "additionalProperties": False}},
    {"name": "mem.get", "description": "Recall facts matching query substring, optionally scoped to a memory profile",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "profile": {"type": "string", "description": "Memory profile id, or '*' / 'all' for all profiles"}}, "required": ["query"], "additionalProperties": False}},
    {"name": "sys.status", "description": "Bridge/services/funnel status",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "skill.list", "description": "List available agent skills",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "skill.run", "description": "Run an agent skill: namespace/name with optional args",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}, "default": []}},
         "required": ["name"], "additionalProperties": False}},
    {"name": "hooks.list", "description": "List configured hooks per event",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    # v4.67.0: namespaced version of the legacy bare ``snapshot``.
    # See the note above on exec.ping/echo/exec for the rationale.
    {"name": "exec.snapshot", "description": "Namespaced alias for ``snapshot``. Run system snapshot skill and return JSON path.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "snapshot", "description": "Run system snapshot skill and return JSON path",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "subagent.spawn", "description": "Spawn isolated subagent for delegated work; returns summary",
     "inputSchema": {"type": "object", "properties": {
         "cmd": {"type": "string"}, "name": {"type": "string"},
         "wait": {"type": "boolean", "default": True}, "timeout": {"type": "integer", "default": 300}},
         "required": ["cmd"], "additionalProperties": False}},
    {"name": "subagent.list", "description": "List recent subagents",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "memory.recall", "description": "Find relevant facts/snapshots/sessions by query (TF score), optionally scoped to a memory profile",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "top": {"type": "integer", "default": 5}, "profile": {"type": "string", "description": "Memory profile id, or '*' / 'all' for all profiles"}},
         "required": ["query"], "additionalProperties": False}},
    {"name": "memory.digest", "description": "Compact markdown digest of recent memory, optionally scoped to a memory profile",
     "inputSchema": {"type": "object", "properties": {"profile": {"type": "string", "description": "Memory profile id, or '*' / 'all' for all profiles"}}, "additionalProperties": False}},
    {"name": "memory.export", "description": "Export memory facts as JSONL text. Includes profile on each line.",
     "inputSchema": {"type": "object", "properties": {"profile": {"type": "string", "description": "Optional profile to export, or '*' / 'all' for all profiles"}}, "additionalProperties": False}},
    {"name": "memory.import", "description": "Import memory facts from JSONL text. Each line is a JSON object with profile, key, value, tags, timestamp.",
     "inputSchema": {"type": "object", "properties": {
         "profile": {"type": "string", "description": "Default profile for imported rows that omit it"},
         "data": {"type": "string", "description": "JSONL text to import"},
         "overwrite": {"type": "boolean", "default": False, "description": "If true, replace existing facts in the targeted profile(s) before import"}},
         "required": ["data"], "additionalProperties": False}},
    {"name": "git.status", "description": "Show git status for a repository.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Path to git repository"},
         "short": {"type": "boolean", "default": False}},
         "required": ["path"], "additionalProperties": False}},
    {"name": "git.diff", "description": "Show git diff (staged or unstaged).",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Path to git repository"},
         "staged": {"type": "boolean", "default": False, "description": "Show staged (cached) changes"},
         "commit": {"type": "string", "description": "Optional commit hash to diff against"}},
         "required": ["path"], "additionalProperties": False}},
    {"name": "git.log", "description": "Show recent git commits.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Path to git repository"},
         "limit": {"type": "integer", "default": 10, "description": "Max commits to show (1-100)"},
         "oneline": {"type": "boolean", "default": True}},
         "required": ["path"], "additionalProperties": False}},
    {"name": "git.commit", "description": "Stage all changes and create a git commit.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Path to git repository"},
         "message": {"type": "string", "description": "Commit message"},
         "add_all": {"type": "boolean", "default": True, "description": "Stage all changes before commit"}},
         "required": ["path", "message"], "additionalProperties": False}},
]

MCP_TOOLS.extend(MOBILE_MCP_TOOLS)
MCP_TOOLS.extend(NET_MCP_TOOLS)
MCP_TOOLS.extend(ASR_MCP_TOOLS)
MCP_TOOLS.extend(DESKTOP_INPUT_MCP_TOOLS)
MCP_TOOLS.extend(MOBILE_EXT_MCP_TOOLS)
MCP_TOOLS.extend(BROWSER_HEADED_MCP_TOOLS)

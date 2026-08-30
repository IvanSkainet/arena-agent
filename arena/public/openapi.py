"""OpenAPI specification builder for public docs endpoints."""
from __future__ import annotations


def _text_schema(*, required: bool = False) -> dict:
    schema: dict = {"type": "string"}
    if required:
        schema.update({"minLength": 1, "pattern": r".*\S.*"})
    else:
        schema["nullable"] = True
    return schema


def _cognitive_request_schemas() -> tuple[dict, dict, dict]:
    common = {
        "goal": _text_schema(required=True),
        "context": _text_schema(),
        "constraints": {
            "type": "array", "items": {"type": "string"}, "nullable": True,
        },
        "memory_profile": _text_schema(),
    }
    plan = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            **common,
            "max_steps": {
                "type": "integer", "minimum": 1, "default": 8, "nullable": True,
            },
        },
        "required": ["goal"],
    }
    react = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            **common,
            "max_iterations": {
                "type": "integer", "minimum": 1, "default": 4, "nullable": True,
            },
            "url": _text_schema(),
        },
        "required": ["goal"],
    }
    reflect = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "goal": _text_schema(required=True),
            "run": {"type": "object", "nullable": True},
            "notes": _text_schema(),
            "outcome": _text_schema(),
        },
        "required": ["goal"],
    }
    return plan, react, reflect


# ---------------------------------------------------------------------
# Universal response contract (#89).
#
# Measured on 221d2742: of 67 documented operations, 62 of the 63 that sit
# behind authentication declared no 401, and 66 declared no schema for their
# success body. A spec that never mentions the error a caller will actually
# hit is not a contract -- it is a brochure.
#
# These responses are not per-endpoint decisions, so they are not written
# per-endpoint. They follow from two pieces of shared machinery:
#
#   * `authed()` (arena/handler_helpers.py) runs `ctx.require_auth` before
#     every wrapped handler and returns whatever it produces, then converts
#     any uncaught exception into a 500 envelope.
#   * `require_auth()` (arena/auth/runtime.py) answers 401 for a bad or
#     absent credential, and 429 once an IP fails ten times in sixty
#     seconds -- with a Retry-After header.
#
# So every authenticated operation can return 401, 429 and 500 whatever else
# it does. Generating them keeps the document honest as routes are added, and
# stops 63 copies of the same three stanzas drifting apart.
#
# Public endpoints are excluded deliberately. The allow-list mirrors
# PUBLIC_BY_DESIGN in tests/test_auth_surface_guard.py, which is enforced by
# execution: that test walks every route the router registered and requires a
# refusal from each one absent from the list. Documenting a 401 on a route
# that never returns one would be a new lie, not a fix.
# ---------------------------------------------------------------------

_PUBLIC_PATHS = frozenset({
    "/", "/health", "/v2/health", "/metrics", "/v1/metrics", "/openapi.json",
    "/api-docs", "/gui", "/gui/v2", "/sse", "/v1/version",
    "/gui/assets/manifest.json", "/mcp", "/messages",
})

_ERROR_ENVELOPE = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean", "enum": [False]},
        "error": {"type": "string"},
        "request_id": {"type": "string"},
    },
    "required": ["ok", "error"],
}


def _error_response(description: str) -> dict:
    return {
        "description": description,
        "content": {"application/json": {"schema": _ERROR_ENVELOPE}},
    }


def _json_schema(properties: dict, required: list[str]) -> dict:
    """A 2xx body description a client generator can actually consume."""
    return {"content": {"application/json": {"schema": {
        "type": "object", "properties": properties, "required": required}}}}


# Success-body schemas for the endpoints whose shape was confirmed by calling
# them in-process (see tests/test_openapi_error_contract_89.py, which re-checks
# every key below against a live response so these cannot silently rot).
#
# Only paths already present in `paths` above can appear here. /v2/health and
# /v1/metrics were measured too, but they are still part of the undocumented
# backlog tracked by the parity ratchet, so their schemas wait for the entry.
_SUCCESS_SCHEMAS: dict[tuple[str, str], tuple[dict, list[str]]] = {
    ("/health", "get"): (
        {"ok": {"type": "boolean"}, "service": {"type": "string"},
         "version": {"type": "string"}, "uptime_seconds": {"type": "number"}},
        ["ok", "service", "version", "uptime_seconds"],
    ),
    ("/v1/version", "get"): (
        {"ok": {"type": "boolean"}, "version": {"type": "string"},
         "service": {"type": "string"}, "loopback_only": {"type": "boolean"},
         "exposed_publicly": {"type": ["boolean", "null"]},
         "deployment": {"type": "object"}},
        ["ok", "version", "service", "loopback_only", "deployment"],
    ),
}


def _apply_success_schemas(spec: dict) -> dict:
    """Attach observed 2xx schemas, never overwriting a richer existing one."""
    for (path, method), (properties, required) in _SUCCESS_SCHEMAS.items():
        operation = spec.get("paths", {}).get(path, {}).get(method)
        if not operation:
            continue
        success = operation.setdefault("responses", {}).setdefault(
            "200", {"description": "Success"})
        if "content" not in success:
            success.update(_json_schema(properties, required))
    return spec


def _apply_universal_responses(spec: dict) -> dict:
    """Attach the responses every authenticated operation can actually return.

    Never overwrites an existing entry: an endpoint that documents its own
    401 or 500 has said something more specific than this function knows.
    """
    methods = ("get", "post", "put", "delete", "patch")
    for path, item in spec["paths"].items():
        if path in _PUBLIC_PATHS:
            continue
        for method, operation in item.items():
            if method not in methods:
                continue
            responses = operation.setdefault("responses", {})
            responses.setdefault("401", _error_response(
                "Missing or invalid credential. The bridge accepts a Bearer "
                "token, an X-Arena-Token header, or (deprecated) a ?token= "
                "query parameter."))
            responses.setdefault("429", {
                "description": (
                    "Too many failed authentication attempts from this IP "
                    "(ten within sixty seconds). Retry-After is set."),
                "headers": {"Retry-After": {"schema": {"type": "string"}}},
                "content": {"application/json": {"schema": _ERROR_ENVELOPE}},
            })
            responses.setdefault("500", _error_response(
                "Unhandled server error. The handler wrapper converts any "
                "uncaught exception into this envelope."))
    return spec


def build_openapi_spec(ctx) -> dict:
    plan_schema, react_schema, reflect_schema = _cognitive_request_schemas()
    spec: dict = {
        "openapi": "3.0.3",
        "info": {
            "title": "Arena Unified Bridge API",
            "version": ctx.version,
            "description": "Unified bridge for AI agent orchestration: exec, files, memory, planner, desktop, browser, tasks, and observability.",
        },
        "servers": [{"url": f"http://{ctx.hostname()}:{ctx.bridge_port()}"}],
        "security": [{"BearerAuth": []}],
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"}
            }
        },
        "paths": {
            "/health": {"get": {"summary": "Health check", "tags": ["Bridge"], "responses": {"200": {"description": "OK"}}}},
            "/v1/version": {"get": {"summary": "Bridge version", "tags": ["Bridge"], "responses": {"200": {"description": "Version info"}}}},
            "/v1/status": {"get": {"summary": "Bridge status", "tags": ["Bridge"], "responses": {"200": {"description": "Status info"}}}},
            "/v1/capabilities": {"get": {"summary": "Agent-facing capability map", "tags": ["System"], "responses": {"200": {"description": "Capabilities by subsystem/backend"}}}},
            "/v1/exec": {"post": {"summary": "Execute command", "tags": ["Exec"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"cmd": {"type": "string"}, "timeout": {"type": "integer", "default": 30}, "cwd": {"type": "string"}}, "required": ["cmd"]}}}}, "responses": {"200": {"description": "Command result"}}}},
            "/v1/upload": {"post": {"summary": "Upload binary file", "tags": ["Files"], "parameters": [{"name": "path", "in": "query", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "Upload result"}}}},
            "/v1/download": {"get": {"summary": "Download file", "tags": ["Files"], "parameters": [{"name": "path", "in": "query", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "File bytes"}}}},
            "/v1/fs/edit": {"patch": {"summary": "Find-and-replace in a text file", "tags": ["Files"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}, "replace_all": {"type": "boolean", "default": False}, "preview": {"type": "boolean", "default": False}}, "required": ["path", "old_text", "new_text"]}}}}, "responses": {"200": {"description": "Preview or applied result"}}}},
            "/v1/fs/edit/apply": {"post": {"summary": "Apply a previewed safe edit", "tags": ["Files"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"preview_id": {"type": "string"}}, "required": ["preview_id"]}}}}, "responses": {"200": {"description": "Applied edit"}}}},
            "/v1/fs/edit/rollback": {"post": {"summary": "Rollback a safe edit", "tags": ["Files"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"rollback_id": {"type": "string"}, "force": {"type": "boolean", "default": False}}, "required": ["rollback_id"]}}}}, "responses": {"200": {"description": "Rollback result"}}}},
            "/v1/fs/view": {"post": {"summary": "Read a text file", "tags": ["Files"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"path": {"type": "string"}, "view_range": {"type": "array", "items": {"type": "integer"}, "maxItems": 2}}, "required": ["path"]}}}}, "responses": {"200": {"description": "View result"}}}},
            "/v1/fs/create": {"post": {"summary": "Create a new text file", "tags": ["Files"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}}}, "responses": {"200": {"description": "Create result"}}}},
            "/v1/memory": {
                "get": {"summary": "List memory facts", "tags": ["Memory"], "parameters": [{"name": "profile", "in": "query", "schema": {"type": "string"}}, {"name": "q", "in": "query", "schema": {"type": "string"}}], "responses": {"200": {"description": "Memory entries"}}},
                "post": {"summary": "Create or update a memory fact", "tags": ["Memory"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"profile": {"type": "string"}, "key": {"type": "string"}, "value": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["key", "value"]}}}}, "responses": {"200": {"description": "Memory fact written"}}},
                "delete": {"summary": "Delete a memory fact", "tags": ["Memory"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"profile": {"type": "string"}, "key": {"type": "string"}}, "required": ["key"]}}}}, "responses": {"200": {"description": "Delete result"}}},
            },
            "/v1/recall": {"get": {"summary": "Recall relevant facts", "tags": ["Memory"], "parameters": [{"name": "q", "in": "query", "required": True, "schema": {"type": "string"}}, {"name": "top", "in": "query", "schema": {"type": "integer", "default": 5}}, {"name": "profile", "in": "query", "schema": {"type": "string"}}], "responses": {"200": {"description": "Recall result"}}}},
            "/v1/recall/digest": {"get": {"summary": "Generate a memory digest", "tags": ["Memory"], "parameters": [{"name": "profile", "in": "query", "schema": {"type": "string"}}], "responses": {"200": {"description": "Digest markdown"}}}},
            "/v1/plan": {"post": {"summary": "Create a structured execution plan for a goal", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": plan_schema}}}, "responses": {"200": {"description": "Planner output"}}}},
            "/v1/react": {"post": {"summary": "Run a bounded reason-act-observe loop", "tags": ["Agentic"], "requestBody": {"content": {"application/json": {"schema": react_schema}}}, "responses": {"200": {"description": "ReAct run output"}}}},
            "/v1/reflect": {"post": {"summary": "Reflect on a prior run", "tags": ["Agentic"], "requestBody": {"content": {"application/json": {"schema": reflect_schema}}}, "responses": {"200": {"description": "Reflection output"}}}},
            "/v1/watch/files": {
                "get": {"summary": "List active file watchers", "tags": ["Watchers"], "responses": {"200": {"description": "Watcher list"}}},
                "post": {"summary": "Add a file watcher", "tags": ["Watchers"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"path": {"type": "string"}, "recursive": {"type": "boolean", "default": True}, "patterns": {"type": "array", "items": {"type": "string"}}, "label": {"type": "string"}}, "required": ["path"]}}}}, "responses": {"200": {"description": "Watcher added"}}},
                "delete": {"summary": "Remove a file watcher", "tags": ["Watchers"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}}}, "responses": {"200": {"description": "Watcher removed"}}},
            },
            "/v1/desktop/screenshot": {"get": {"summary": "Take desktop screenshot", "tags": ["Desktop"], "parameters": [{"name": "format", "in": "query", "schema": {"type": "string", "enum": ["base64", "png", "jpeg", "jpg", "webp"], "default": "base64"}}, {"name": "display", "in": "query", "schema": {"type": "string"}}, {"name": "region_x", "in": "query", "schema": {"type": "integer"}}, {"name": "region_y", "in": "query", "schema": {"type": "integer"}}, {"name": "region_width", "in": "query", "schema": {"type": "integer"}}, {"name": "region_height", "in": "query", "schema": {"type": "integer"}}, {"name": "scale", "in": "query", "schema": {"type": "number"}}, {"name": "max_width", "in": "query", "schema": {"type": "integer"}}, {"name": "quality", "in": "query", "schema": {"type": "integer", "default": 80}}], "responses": {"200": {"description": "Screenshot data"}}}},
            "/v1/desktop/displays": {"get": {"summary": "List desktop displays/outputs", "tags": ["Desktop"], "responses": {"200": {"description": "Display geometry and output metadata"}}}},
            "/v1/desktop/windows": {"get": {"summary": "List desktop windows", "tags": ["Desktop"], "parameters": [{"name": "title", "in": "query", "schema": {"type": "string"}}, {"name": "class", "in": "query", "schema": {"type": "string"}}, {"name": "desktop_file", "in": "query", "schema": {"type": "string"}}, {"name": "resource_name", "in": "query", "schema": {"type": "string"}}, {"name": "pid", "in": "query", "schema": {"type": "integer"}}, {"name": "display", "in": "query", "schema": {"type": "string"}}, {"name": "active_only", "in": "query", "schema": {"type": "boolean"}}, {"name": "include_displays", "in": "query", "schema": {"type": "boolean"}}], "responses": {"200": {"description": "Window list"}}}},
            "/v1/desktop/active_window": {"get": {"summary": "Get active desktop window", "tags": ["Desktop"], "responses": {"200": {"description": "Active window details"}}}},
            "/v1/desktop/focus": {"post": {"summary": "Focus a desktop window by id, semantic filters, or OCR text query", "tags": ["Desktop"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "string"}, "query": {"type": "string"}, "title": {"type": "string"}, "class": {"type": "string"}, "desktop_file": {"type": "string"}, "resource_name": {"type": "string"}, "pid": {"type": "integer"}, "display": {"type": "string"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": True}, "within_active_window": {"type": "boolean", "default": False}, "crop_active_window": {"type": "boolean", "default": True}, "verify": {"type": "boolean", "default": True}, "timeout_ms": {"type": "integer", "default": 1500}, "dry_run": {"type": "boolean", "default": False}}}}}}, "responses": {"200": {"description": "Focus result"}, "404": {"description": "No window matched"}}}},
            "/v1/desktop/window_action": {"post": {"summary": "Move, resize, minimize, maximize, restore, close, center, snap, move to another display, or toggle fullscreen on a desktop window", "tags": ["Desktop"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["minimize", "restore", "maximize", "unmaximize", "fullscreen", "unfullscreen", "close", "center", "move_to_display", "snap_left", "snap_right", "snap_top", "snap_bottom", "snap_top_left", "snap_top_right", "snap_bottom_left", "snap_bottom_right", "move", "resize", "move_resize"]}, "id": {"type": "string"}, "query": {"type": "string"}, "title": {"type": "string"}, "class": {"type": "string"}, "desktop_file": {"type": "string"}, "resource_name": {"type": "string"}, "pid": {"type": "integer"}, "display": {"type": "string"}, "target_display": {"type": "string"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": True}, "within_active_window": {"type": "boolean", "default": False}, "crop_active_window": {"type": "boolean", "default": True}, "x": {"type": "integer"}, "y": {"type": "integer"}, "width": {"type": "integer"}, "height": {"type": "integer"}, "verify": {"type": "boolean", "default": True}, "timeout_ms": {"type": "integer", "default": 1000}, "dry_run": {"type": "boolean", "default": False}}, "required": ["action"]}}}}, "responses": {"200": {"description": "Window action result"}, "404": {"description": "No window matched"}}}},
            "/v1/desktop/resolve_text_target": {"post": {"summary": "Resolve OCR text into a containing window target", "tags": ["Desktop"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"query": {"type": "string"}, "display": {"type": "string"}, "title": {"type": "string"}, "class": {"type": "string"}, "desktop_file": {"type": "string"}, "resource_name": {"type": "string"}, "pid": {"type": "integer"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": True}, "within_active_window": {"type": "boolean", "default": False}, "crop_active_window": {"type": "boolean", "default": True}}, "required": ["query"]}}}}, "responses": {"200": {"description": "Resolved text target"}, "404": {"description": "No text or containing window matched"}}}},
            "/v1/desktop/text_action": {"post": {"summary": "Resolve visible text and run a high-level desktop action", "tags": ["Desktop"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["resolve", "focus", "click", "center", "move_to_display", "snap_left", "snap_right", "snap_top", "snap_bottom", "snap_top_left", "snap_top_right", "snap_bottom_left", "snap_bottom_right", "minimize", "restore", "maximize", "unmaximize", "fullscreen", "unfullscreen", "close", "move", "resize", "move_resize"], "default": "resolve"}, "query": {"type": "string"}, "display": {"type": "string"}, "target_display": {"type": "string"}, "title": {"type": "string"}, "class": {"type": "string"}, "desktop_file": {"type": "string"}, "resource_name": {"type": "string"}, "pid": {"type": "integer"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": True}, "within_active_window": {"type": "boolean", "default": False}, "crop_active_window": {"type": "boolean", "default": True}, "target_position": {"type": "string", "enum": ["center", "left", "right", "top", "bottom"], "default": "center"}, "offset_x": {"type": "integer", "default": 0}, "offset_y": {"type": "integer", "default": 0}, "button": {"type": "string", "default": "left"}, "double": {"type": "boolean", "default": False}, "activate": {"type": "boolean", "default": True}, "verify": {"type": "boolean", "default": True}, "timeout_ms": {"type": "integer", "default": 1000}, "dry_run": {"type": "boolean", "default": False}}, "required": ["query"]}}}}, "responses": {"200": {"description": "Resolved text workflow result"}, "404": {"description": "No text or containing window matched"}}}},
            "/v1/desktop/ocr": {"post": {"summary": "Run OCR on a fresh desktop screenshot", "tags": ["Desktop"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"query": {"type": "string"}, "display": {"type": "string"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": False}, "within_active_window": {"type": "boolean", "default": False}}}}}}, "responses": {"200": {"description": "OCR text, words, and optional matches"}}}},
            "/v1/desktop/find_text": {"post": {"summary": "Find text on the current desktop", "tags": ["Desktop"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"query": {"type": "string"}, "display": {"type": "string"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": False}, "within_active_window": {"type": "boolean", "default": False}}, "required": ["query"]}}}}, "responses": {"200": {"description": "Match results"}, "404": {"description": "No match found"}}}},
            "/v1/desktop/click_text": {"post": {"summary": "Find text on the current desktop and click the best match", "tags": ["Desktop"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"query": {"type": "string"}, "display": {"type": "string"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}, "prefer_active_window": {"type": "boolean", "default": True}, "within_active_window": {"type": "boolean", "default": False}, "target_position": {"type": "string", "enum": ["center", "left", "right", "top", "bottom"], "default": "center"}, "offset_x": {"type": "integer", "default": 0}, "offset_y": {"type": "integer", "default": 0}, "button": {"type": "string", "default": "left"}, "double": {"type": "boolean", "default": False}, "activate": {"type": "boolean", "default": True}, "dry_run": {"type": "boolean", "default": False}}, "required": ["query"]}}}}, "responses": {"200": {"description": "Click result"}, "404": {"description": "No match found"}}}},
            "/v1/browser/head": {"get": {"summary": "HTTP HEAD request", "tags": ["Browser"], "responses": {"200": {"description": "HEAD result"}}}},
            "/v1/tasks": {"get": {"summary": "List tasks", "tags": ["Tasks"], "responses": {"200": {"description": "Task list"}}}, "post": {"summary": "Create task", "tags": ["Tasks"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"cmd": {"type": "string"}, "title": {"type": "string"}}}}}}, "responses": {"200": {"description": "Task created"}}}},
            "/v1/mission/status": {"get": {"summary": "Get structured mission status", "tags": ["Planner"], "parameters": [{"name": "name", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Mission name or id. Either this or mission_id is required; a short scenario name resolves to its stored mission."}, {"name": "mission_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Alias of name (#130)."}], "responses": {"200": {"description": "Mission status"}, "404": {"description": "Mission not found"}}}},
            "/v1/mission/report": {"get": {"summary": "Read a mission report", "tags": ["Planner"], "parameters": [{"name": "name", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Mission name or id. Either this or mission_id is required; a short scenario name resolves to its stored mission."}, {"name": "mission_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Alias of name (#130)."}], "responses": {"200": {"description": "Mission report"}, "404": {"description": "Mission report not found"}}}},
            "/v1/mission/history": {"get": {"summary": "Inspect mission run history and step log summaries", "tags": ["Planner"], "parameters": [{"name": "name", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Mission name or id. Either this or mission_id is required; a short scenario name resolves to its stored mission."}, {"name": "mission_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Alias of name (#130)."}], "responses": {"200": {"description": "Mission history"}, "404": {"description": "Mission not found"}}}},
            "/v1/mission/lineage": {"get": {"summary": "Inspect mission parent/child lineage and descendants", "tags": ["Planner"], "parameters": [{"name": "name", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Mission name or id. Either this or mission_id is required; a short scenario name resolves to its stored mission."}, {"name": "mission_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Alias of name (#130)."}], "responses": {"200": {"description": "Mission lineage"}, "404": {"description": "Mission not found"}}}},
            "/v1/mission/family": {"get": {"summary": "Inspect the full mission family rooted at a mission chain", "tags": ["Planner"], "parameters": [{"name": "name", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Mission name or id. Either this or mission_id is required; a short scenario name resolves to its stored mission."}, {"name": "mission_id", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Alias of name (#130)."}], "responses": {"200": {"description": "Mission family"}, "404": {"description": "Mission not found"}}}},
            "/v1/mission/catalog": {"get": {"summary": "List persisted missions with lifecycle filters and summary stats", "tags": ["Planner"], "parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}, {"name": "state", "in": "query", "schema": {"type": "string"}}, {"name": "template", "in": "query", "schema": {"type": "string"}}, {"name": "has_report", "in": "query", "schema": {"type": "boolean"}}, {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}}, {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}}], "responses": {"200": {"description": "Mission catalog"}}}},
            "/v1/mission/schedules": {"get": {"summary": "List mission schedules", "tags": ["Planner"], "parameters": [{"name": "action", "in": "query", "schema": {"type": "string"}}, {"name": "enabled", "in": "query", "schema": {"type": "boolean"}}, {"name": "due_only", "in": "query", "schema": {"type": "boolean"}}, {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100}}], "responses": {"200": {"description": "Mission schedules"}}}, "post": {"summary": "Create or update a mission schedule", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"schedule_id": {"type": "string"}, "mission_id": {"type": "string"}, "action": {"type": "string", "enum": ["run", "rerun_failed", "iterate"]}, "every_minutes": {"type": "integer", "default": 60}, "enabled": {"type": "boolean", "default": True}, "title": {"type": "string"}, "notes": {"type": "string"}, "followup_goal": {"type": "string"}, "followup_title": {"type": "string"}, "constraints": {"type": "array", "items": {"type": "string"}}, "memory_profile": {"type": "string"}, "template": {"type": "string"}, "max_steps": {"type": "integer", "default": 8}, "max_iterations": {"type": "integer", "default": 4}, "next_run_at": {"type": "string"}}, "required": ["mission_id"]}}}}, "responses": {"200": {"description": "Saved mission schedule"}}}, "delete": {"summary": "Delete a mission schedule", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"schedule_id": {"type": "string"}, "id": {"type": "string"}}, "required": ["schedule_id"]}}}}, "responses": {"200": {"description": "Deleted mission schedule"}}}},
            "/v1/mission/schedules/state": {"get": {"summary": "Read mission schedule worker state", "tags": ["Planner"], "responses": {"200": {"description": "Mission schedule worker state"}}}},
            "/v1/mission/templates": {"get": {"summary": "List built-in mission templates", "tags": ["Planner"], "responses": {"200": {"description": "Mission template catalog"}}}},
            "/v1/mission/compose": {"post": {"summary": "Compose a planner-backed mission draft", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"goal": {"type": "string"}, "context": {"type": "string"}, "constraints": {"type": "array", "items": {"type": "string"}}, "max_steps": {"type": "integer", "default": 8}, "memory_profile": {"type": "string"}, "title": {"type": "string"}, "template": {"type": "string"}}, "required": ["goal"]}}}}, "responses": {"200": {"description": "Mission draft"}}}},
            "/v1/mission/propose": {"post": {"summary": "Run a bounded agentic proposal flow and return a planner-backed mission bundle", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"goal": {"type": "string"}, "context": {"type": "string"}, "constraints": {"type": "array", "items": {"type": "string"}}, "max_steps": {"type": "integer", "default": 8}, "max_iterations": {"type": "integer", "default": 4}, "memory_profile": {"type": "string"}, "url": {"type": "string"}, "title": {"type": "string"}, "template": {"type": "string"}, "notes": {"type": "string"}, "create": {"type": "boolean", "default": False}, "run_now": {"type": "boolean", "default": False}, "mission_id": {"type": "string"}, "overwrite": {"type": "boolean", "default": False}, "timeout": {"type": "integer", "default": 180}}, "required": ["goal"]}}}}, "responses": {"200": {"description": "Mission proposal bundle"}}}},
            "/v1/mission/create": {"post": {"summary": "Create a persisted mission from a draft", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"draft": {"type": "object"}, "goal": {"type": "string"}, "context": {"type": "string"}, "constraints": {"type": "array", "items": {"type": "string"}}, "max_steps": {"type": "integer", "default": 8}, "memory_profile": {"type": "string"}, "title": {"type": "string"}, "template": {"type": "string"}, "mission_id": {"type": "string"}, "overwrite": {"type": "boolean", "default": False}}}}}}, "responses": {"200": {"description": "Created mission"}}}},
            "/v1/mission/run": {"post": {"summary": "Run a persisted mission", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"mission_id": {"type": "string"}, "step": {"type": "integer"}, "timeout": {"type": "integer", "default": 180}}, "required": ["mission_id"]}}}}, "responses": {"200": {"description": "Mission run result"}}}},
            "/v1/mission/rerun": {"post": {"summary": "Rerun a mission, optionally just the last failed step", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"mission_id": {"type": "string"}, "step": {"type": "integer"}, "failed_only": {"type": "boolean", "default": False}, "timeout": {"type": "integer", "default": 180}}, "required": ["mission_id"]}}}}, "responses": {"200": {"description": "Mission rerun result"}}}},
            "/v1/mission/recover": {"post": {"summary": "Build a recovery bundle for a persisted mission, with optional rerun and follow-up composition", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"mission_id": {"type": "string"}, "notes": {"type": "string"}, "failed_only": {"type": "boolean", "default": True}, "step": {"type": "integer"}, "timeout": {"type": "integer", "default": 180}, "rerun_now": {"type": "boolean", "default": False}, "compose_followup": {"type": "boolean", "default": False}, "create_followup": {"type": "boolean", "default": False}, "followup_goal": {"type": "string"}, "followup_title": {"type": "string"}, "followup_mission_id": {"type": "string"}, "max_steps": {"type": "integer", "default": 8}, "memory_profile": {"type": "string"}, "template": {"type": "string"}, "overwrite": {"type": "boolean", "default": False}}, "required": ["mission_id"]}}}}, "responses": {"200": {"description": "Mission recovery bundle"}}}},
            "/v1/mission/followup": {"post": {"summary": "Compose a next mission from an existing mission's artifacts using agentic analysis", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"mission_id": {"type": "string"}, "goal": {"type": "string"}, "title": {"type": "string"}, "notes": {"type": "string"}, "constraints": {"type": "array", "items": {"type": "string"}}, "max_steps": {"type": "integer", "default": 8}, "max_iterations": {"type": "integer", "default": 4}, "memory_profile": {"type": "string"}, "template": {"type": "string"}, "url": {"type": "string"}, "create": {"type": "boolean", "default": False}, "run_now": {"type": "boolean", "default": False}, "followup_mission_id": {"type": "string"}, "overwrite": {"type": "boolean", "default": False}, "timeout": {"type": "integer", "default": 180}}, "required": ["mission_id"]}}}}, "responses": {"200": {"description": "Mission follow-up bundle"}}}},
            "/v1/mission/iterate": {"post": {"summary": "Run a full mission iteration loop: recover current mission, then optionally compose/create/run a follow-up mission", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"mission_id": {"type": "string"}, "notes": {"type": "string"}, "failed_only": {"type": "boolean", "default": True}, "step": {"type": "integer"}, "timeout": {"type": "integer", "default": 180}, "rerun_now": {"type": "boolean", "default": False}, "compose_followup": {"type": "boolean", "default": False}, "create_followup": {"type": "boolean", "default": False}, "run_followup": {"type": "boolean", "default": False}, "followup_goal": {"type": "string"}, "followup_title": {"type": "string"}, "followup_mission_id": {"type": "string"}, "constraints": {"type": "array", "items": {"type": "string"}}, "max_steps": {"type": "integer", "default": 8}, "max_iterations": {"type": "integer", "default": 4}, "memory_profile": {"type": "string"}, "template": {"type": "string"}, "url": {"type": "string"}, "overwrite": {"type": "boolean", "default": False}}, "required": ["mission_id"]}}}}, "responses": {"200": {"description": "Mission iteration bundle"}}}},
            "/v1/mission/schedules/tick": {"post": {"summary": "Manually execute due mission schedules", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"schedule_id": {"type": "string"}, "id": {"type": "string"}, "force": {"type": "boolean", "default": False}, "limit": {"type": "integer", "default": 10}, "timeout": {"type": "integer", "default": 180}}}}}}, "responses": {"200": {"description": "Mission schedule tick result"}}}},
            "/v1/extension/policies": {"get": {"summary": "Read browser chat extension execution policies", "tags": ["Planner"], "responses": {"200": {"description": "Extension policy snapshot"}}}},
            "/v1/extension/preview": {"post": {"summary": "Validate and preview an Arena browser-extension execution payload", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}, "required": True}, "responses": {"200": {"description": "Extension preview result"}}}},
            "/v1/extension/execute": {"post": {"summary": "Execute an Arena browser-extension payload through tool policy checks", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}, "required": True}, "responses": {"200": {"description": "Extension execute result"}}}},
            "/v1/exec/script": {"post": {"summary": "Execute a raw script body", "description": "The body is the script itself, not JSON. The interpreter is chosen with the X-Arena-Interpreter header; X-Arena-Timeout and X-Arena-Cwd override the defaults. Refused with 403 on the cautious profile: raw scripts cannot be inspected for semantics.", "tags": ["Exec"], "parameters": [{"name": "X-Arena-Interpreter", "in": "header", "schema": {"type": "string"}, "description": "Interpreter key, e.g. powershell, bash, python"}, {"name": "X-Arena-Timeout", "in": "header", "schema": {"type": "integer"}}, {"name": "X-Arena-Cwd", "in": "header", "schema": {"type": "string"}}], "requestBody": {"required": True, "content": {"text/plain": {"schema": {"type": "string"}}}}, "responses": {"200": {"description": "Script result"}, "400": {"description": "Empty body, unsupported interpreter, or interpreter unavailable on this OS"}, "403": {"description": "Refused by the active profile or the control-character gate"}, "408": {"description": "Timed out"}, "413": {"description": "Script body above the 5 MiB cap"}}}},
            "/v1/exec/stream": {"post": {"summary": "Execute a command, streaming output", "tags": ["Exec"], "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "properties": {"cmd": {"type": "string"}, "timeout": {"type": "integer", "default": 30}, "cwd": {"type": "string"}}, "required": ["cmd"]}}}}, "responses": {"200": {"description": "Chunked stream of command output"}, "400": {"description": "Missing cmd"}, "403": {"description": "Refused by the active profile or the control-character gate"}}}},
            "/v1/token/regenerate": {"post": {"summary": "Rotate the bridge bearer token", "description": "Generates a new master token, writes it to the token file, and invalidates the current one from the next request onward. No restart is required. A write failure is ALSO reported with HTTP 200 and ok=false, so the caller must inspect ok before discarding the credential it currently holds.", "tags": ["Bridge"], "responses": {"200": {"description": "Rotation outcome. ok=true carries the new token in `token`; ok=false means the token file could not be written and the CURRENT credential is still valid -- do not discard it.", "content": {"application/json": {"schema": {"type": "object", "properties": {"ok": {"type": "boolean"}, "token": {"type": "string", "description": "Present only when ok is true"}, "written_to": {"type": "array", "items": {"type": "string"}}, "previous_token_revoked": {"type": "boolean"}, "restart_required": {"type": "boolean"}, "error": {"type": "string", "description": "Present only when ok is false"}}, "required": ["ok"]}}}}, }}},
            "/v1/events": {"get": {"summary": "WebSocket real-time event stream", "tags": ["Events"], "responses": {"200": {"description": "WebSocket upgrade for events"}}}},
            "/gui": {"get": {"summary": "Web dashboard", "tags": ["Bridge"], "responses": {"200": {"description": "HTML dashboard"}}}},
            "/api-docs": {"get": {"summary": "OpenAPI specification", "tags": ["Bridge"], "responses": {"200": {"description": "OpenAPI JSON"}}}},
            "/openapi.json": {"get": {"summary": "OpenAPI specification alias", "tags": ["Bridge"], "responses": {"200": {"description": "OpenAPI JSON"}}}},
        },
        "tags": [
            {"name": "Bridge", "description": "Core bridge operations"},
            {"name": "System", "description": "System information and diagnostics"},
            {"name": "Exec", "description": "Command execution"},
            {"name": "Files", "description": "File upload, download, safe editing, and surgical editing"},
            {"name": "Memory", "description": "Memory and recall"},
            {"name": "Planner", "description": "Structured task planning"},
            {"name": "Agentic", "description": "Bounded ReAct loops and reflection"},
            {"name": "Watchers", "description": "Realtime file watchers and file-change events"},
            {"name": "Desktop", "description": "Desktop screenshot, OCR, text targeting, input, focus, and control lease"},
            {"name": "Browser", "description": "Browser and web helpers"},
            {"name": "Tasks", "description": "Task management"},
            {"name": "Events", "description": "Real-time WebSocket event stream"},
        ],
    }
    return _apply_success_schemas(_apply_universal_responses(spec))

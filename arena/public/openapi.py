"""OpenAPI specification builder for public docs endpoints."""
from __future__ import annotations


def build_openapi_spec(ctx) -> dict:
    return {
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
            "/v1/plan": {"post": {"summary": "Create a structured execution plan for a goal", "tags": ["Planner"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"goal": {"type": "string"}, "context": {"type": "string"}, "constraints": {"type": "array", "items": {"type": "string"}}, "max_steps": {"type": "integer", "default": 8}, "memory_profile": {"type": "string"}}, "required": ["goal"]}}}}, "responses": {"200": {"description": "Planner output"}}}},
            "/v1/react": {"post": {"summary": "Run a bounded reason-act-observe loop", "tags": ["Agentic"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"goal": {"type": "string"}, "context": {"type": "string"}, "constraints": {"type": "array", "items": {"type": "string"}}, "max_iterations": {"type": "integer", "default": 4}, "memory_profile": {"type": "string"}, "url": {"type": "string"}}, "required": ["goal"]}}}}, "responses": {"200": {"description": "ReAct run output"}}}},
            "/v1/reflect": {"post": {"summary": "Reflect on a prior run", "tags": ["Agentic"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"goal": {"type": "string"}, "run": {"type": "object"}, "notes": {"type": "string"}, "outcome": {"type": "string"}}}}}}, "responses": {"200": {"description": "Reflection output"}}}},
            "/v1/watch/files": {
                "get": {"summary": "List active file watchers", "tags": ["Watchers"], "responses": {"200": {"description": "Watcher list"}}},
                "post": {"summary": "Add a file watcher", "tags": ["Watchers"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"path": {"type": "string"}, "recursive": {"type": "boolean", "default": True}, "patterns": {"type": "array", "items": {"type": "string"}}, "label": {"type": "string"}}, "required": ["path"]}}}}, "responses": {"200": {"description": "Watcher added"}}},
                "delete": {"summary": "Remove a file watcher", "tags": ["Watchers"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}}}, "responses": {"200": {"description": "Watcher removed"}}},
            },
            "/v1/desktop/screenshot": {"get": {"summary": "Take desktop screenshot", "tags": ["Desktop"], "parameters": [{"name": "format", "in": "query", "schema": {"type": "string", "enum": ["base64", "png", "jpeg", "jpg", "webp"], "default": "base64"}}, {"name": "scale", "in": "query", "schema": {"type": "number"}}, {"name": "max_width", "in": "query", "schema": {"type": "integer"}}, {"name": "quality", "in": "query", "schema": {"type": "integer", "default": 80}}], "responses": {"200": {"description": "Screenshot data"}}}},
            "/v1/desktop/ocr": {"post": {"summary": "Run OCR on a fresh desktop screenshot", "tags": ["Desktop"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"query": {"type": "string"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}}}}}}, "responses": {"200": {"description": "OCR text, words, and optional matches"}}}},
            "/v1/desktop/find_text": {"post": {"summary": "Find text on the current desktop", "tags": ["Desktop"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"query": {"type": "string"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}, "min_confidence": {"type": "integer", "default": 40}, "psm": {"type": "integer", "default": 11}, "max_results": {"type": "integer", "default": 20}}, "required": ["query"]}}}}, "responses": {"200": {"description": "Match results"}, "404": {"description": "No match found"}}}},
            "/v1/browser/head": {"get": {"summary": "HTTP HEAD request", "tags": ["Browser"], "responses": {"200": {"description": "HEAD result"}}}},
            "/v1/tasks": {"get": {"summary": "List tasks", "tags": ["Tasks"], "responses": {"200": {"description": "Task list"}}}, "post": {"summary": "Create task", "tags": ["Tasks"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"cmd": {"type": "string"}, "title": {"type": "string"}}}}}}, "responses": {"200": {"description": "Task created"}}}},
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

"""Public bridge endpoints: index, health and OpenAPI docs."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import PublicHandlerContext

PUBLIC_ENDPOINTS = [
    "/health", "/v1/version", "/v1/info", "/v1/status", "/v1/sysinfo",
    "/v1/capabilities", "/v1/hardware", "/v1/hwinfo", "/v1/inventory?section=&format=text|json",
    "/v1/ps", "/v1/audit?lines=100", "/v1/audit/stats",
    "POST /v1/exec", "POST /v1/kill",
    "POST /v1/upload?path=", "GET /v1/download?path=",
    "GET /v1/memory?q=", "POST /v1/memory",
    "GET /v1/missions", "GET /v1/mission/show?name=",
    "GET /v1/reports", "GET /v1/doctor", "POST /v1/beep",
    "GET /v1/browser/search?q=", "GET /v1/browser/read?url=",
    "GET /v1/browser/dump?url=", "GET /v1/browser/fetch?url=",
    "GET /v1/browser/head?url=",
    "GET /v1/browser/cdp/status", "POST /v1/browser/cdp/connect", "POST /v1/browser/cdp/disconnect",
    "POST /v1/browser/cdp/navigate", "GET /v1/browser/cdp/screenshot", "GET /v1/browser/cdp/dom",
    "POST /v1/browser/cdp/eval", "POST /v1/browser/cdp/click (selector|x,y)", "POST /v1/browser/cdp/type",
    "GET /v1/desktop/screenshot", "POST /v1/desktop/click", "POST /v1/desktop/type",
    "POST /v1/desktop/key", "POST /v1/desktop/mouse", "GET /v1/desktop/windows",
    "GET /v1/desktop/active_window", "POST /v1/desktop/focus",
    "GET /v1/control/status", "POST /v1/control/pause", "POST /v1/control/resume", "POST /v1/control/revoke",
    "GET /v1/browser/cdp/tabs", "POST /v1/browser/cdp/tabs/new", "POST /v1/browser/cdp/tabs/close",
    "POST /v1/browser/cdp/tabs/activate", "GET/POST/DELETE /v1/browser/cdp/cookies",
    "POST /v1/browser/cdp/cookies/clear", "GET/POST /v1/browser/cdp/cookies/profiles",
    "POST /v1/browser/cdp/network/start", "POST /v1/browser/cdp/network/stop",
    "GET /v1/browser/cdp/network/requests", "GET /v1/browser/cdp/network/har",
    "POST /v1/browser/cdp/intercept/start", "POST /v1/browser/cdp/intercept/stop",
    "POST/DELETE/GET /v1/browser/cdp/intercept/rule|rules",
    "GET /v1/browser/cdp/session/check", "GET/POST /v1/cdp/* aliases",
    "GET /v1/recall?q=&top=5", "GET /v1/recall/digest",
    "GET /v1/tasks?status=&limit=20", "POST /v1/tasks", "POST /v1/tasks/clean",
    "GET /v1/skills", "POST /v1/skills/run",
    "GET /v1/hooks", "GET /v1/agents",
    "GET /v1/subagents", "POST /v1/subagents/spawn",
    "GET /v1/sys/svc", "GET /v1/sys/funnel",
    "GET /v1/service/info",
    "POST /v1/token/regenerate",
    "POST /v1/tailscale/funnel/{start|stop|status}",
    "POST /v1/restart",
    "GET /v1/config",
    "GET /v1/metrics",
    "/gui", "POST /mcp", "DELETE /mcp",
    "GET /sse", "POST /messages", "GET /ws",
    "/gateway", "/gateway/tools", "POST /run", "POST /tool",
]


@dataclass(frozen=True)
class PublicHandlers:
    index: object
    health: object
    api_docs: object


def make_public_handlers(ctx: PublicHandlerContext) -> PublicHandlers:
    async def handle_index(request: web.Request) -> web.Response:
        try:
            ctx.record_request()
            return ctx.cors_json_response({
                "ok": True,
                "service": "arena-unified-bridge",
                "version": ctx.version,
                "endpoints": PUBLIC_ENDPOINTS,
                "auth_required_for_exec": True,
            })
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_health(request: web.Request) -> web.Response:
        try:
            ctx.record_request()
            return ctx.cors_json_response({
                "ok": True,
                "service": "arena-unified-bridge",
                "version": ctx.version,
                "uptime_seconds": round(ctx.now() - ctx.metrics["start_time"], 1),
            })
        except Exception:
            return ctx.cors_json_response({"ok": False, "service": "arena-unified-bridge"}, status=500)

    async def handle_api_docs(request: web.Request) -> web.Response:
        """GET /api-docs — OpenAPI 3.0 specification for all bridge endpoints."""
        spec = {
            "openapi": "3.0.3",
            "info": {
                "title": "Arena Unified Bridge API",
                "version": ctx.version,
                "description": "Unified bridge for AI agent orchestration: CDP browser control, BrowserAct stealth browsing, SuperPowers skills, task management, and system monitoring."
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
                "/v1/info": {"get": {"summary": "Bridge info", "tags": ["Bridge"], "responses": {"200": {"description": "Detailed info"}}}},
                "/v1/metrics": {"get": {"summary": "Bridge metrics (JSON)", "tags": ["Bridge"], "responses": {"200": {"description": "Metrics JSON"}}}},
                "/v1/capabilities": {"get": {"summary": "Agent-facing capability map", "tags": ["System"], "responses": {"200": {"description": "Capabilities by subsystem/backend"}}}},
                "/v1/hardware": {"get": {"summary": "Canonical rich hardware/system inventory", "tags": ["System"], "responses": {"200": {"description": "Normalized hardware inventory"}}}},
                "/v1/hwinfo": {"get": {"summary": "Compatibility alias for /v1/hardware", "tags": ["System"], "responses": {"200": {"description": "Hardware inventory"}}}},
                "/metrics": {"get": {"summary": "Prometheus metrics (text)", "tags": ["Bridge"], "responses": {"200": {"description": "Prometheus text format"}}}},
                "/v1/browser/cdp/status": {"get": {"summary": "CDP connection status", "tags": ["CDP"], "responses": {"200": {"description": "CDP status"}}}},
                "/v1/cdp/status": {"get": {"summary": "Alias for /v1/browser/cdp/status", "tags": ["CDP"], "responses": {"200": {"description": "CDP status"}}}},
                "/v1/browser/cdp/diag": {"get": {"summary": "CDP diagnostics", "tags": ["CDP"], "responses": {"200": {"description": "Diagnostic info"}}}},
                "/v1/browser/cdp/health": {"get": {"summary": "CDP health dashboard", "tags": ["CDP"], "responses": {"200": {"description": "Health info with reconnect history"}}}},
                "/v1/browser/cdp/connect": {"post": {"summary": "Connect to browser via CDP", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"port": {"type": "integer", "default": 9222}, "headless": {"type": "boolean", "default": True}}}}}}, "responses": {"200": {"description": "Connected"}}}},
                "/v1/browser/cdp/disconnect": {"post": {"summary": "Disconnect CDP", "tags": ["CDP"], "responses": {"200": {"description": "Disconnected"}}}},
                "/v1/browser/cdp/navigate": {"post": {"summary": "Navigate to URL", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"url": {"type": "string"}}}}}}, "responses": {"200": {"description": "Navigation result"}}}},
                "/v1/browser/cdp/eval": {"post": {"summary": "Evaluate JavaScript", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"expression": {"type": "string"}}}}}}, "responses": {"200": {"description": "Eval result"}}}},
                "/v1/browser/cdp/screenshot": {"post": {"summary": "Take screenshot", "tags": ["CDP"], "responses": {"200": {"description": "Screenshot data"}}}},
                "/v1/browser/cdp/dom": {"get": {"summary": "Dump DOM", "tags": ["CDP"], "responses": {"200": {"description": "DOM HTML"}}}},
                "/v1/browser/cdp/tabs": {"get": {"summary": "List browser tabs", "tags": ["CDP"], "responses": {"200": {"description": "Tab list"}}}},
                "/v1/browser/cdp/tabs/new": {"post": {"summary": "Open new tab", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"url": {"type": "string"}, "activate": {"type": "boolean"}}}}}}, "responses": {"200": {"description": "New tab info"}}}},
                "/v1/browser/cdp/tabs/close": {"post": {"summary": "Close tab", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"tab_id": {"type": "string"}}}}}}, "responses": {"200": {"description": "Close result"}}}},
                "/v1/browser/cdp/tabs/activate": {"post": {"summary": "Activate tab", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"tab_id": {"type": "string"}}}}}}, "responses": {"200": {"description": "Activation result"}}}},
                "/v1/browser/cdp/click": {"post": {"summary": "Click element", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"selector": {"type": "string"}}}}}}, "responses": {"200": {"description": "Click result"}}}},
                "/v1/browser/cdp/type": {"post": {"summary": "Type text into element", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"selector": {"type": "string"}, "text": {"type": "string"}}}}}}, "responses": {"200": {"description": "Type result"}}}},
                "/v1/browser/cdp/cookies": {"get": {"summary": "Get cookies", "tags": ["CDP"], "responses": {"200": {"description": "Cookie list"}}}},
                "/v1/browser/cdp/cookies/set": {"post": {"summary": "Set cookies", "tags": ["CDP"], "responses": {"200": {"description": "Set result"}}}},
                "/v1/browser/cdp/cookies/delete": {"post": {"summary": "Delete cookies", "tags": ["CDP"], "responses": {"200": {"description": "Delete result"}}}},
                "/v1/browser/cdp/cookies/clear": {"post": {"summary": "Clear all cookies", "tags": ["CDP"], "responses": {"200": {"description": "Clear result"}}}},
                "/v1/browser/cdp/network/start": {"post": {"summary": "Start network monitoring", "tags": ["CDP"], "responses": {"200": {"description": "Monitor started"}}}},
                "/v1/browser/cdp/network/stop": {"post": {"summary": "Stop network monitoring", "tags": ["CDP"], "responses": {"200": {"description": "Monitor stopped"}}}},
                "/v1/browser/cdp/network/requests": {"get": {"summary": "Get captured network requests", "tags": ["CDP"], "responses": {"200": {"description": "Request list"}}}},
                "/v1/browser/cdp/network/har": {"get": {"summary": "Get HAR export", "tags": ["CDP"], "responses": {"200": {"description": "HAR data"}}}},
                "/v1/browser/cdp/intercept/start": {"post": {"summary": "Start request interception", "tags": ["CDP"], "responses": {"200": {"description": "Interception started"}}}},
                "/v1/browser/cdp/intercept/stop": {"post": {"summary": "Stop request interception", "tags": ["CDP"], "responses": {"200": {"description": "Interception stopped"}}}},
                "/v1/browser/cdp/stealth/extract": {"post": {"summary": "Stealth extract page content via CDP", "tags": ["CDP Stealth"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"url": {"type": "string"}, "wait_for": {"type": "string"}, "timeout": {"type": "number", "default": 15}}}}}}, "responses": {"200": {"description": "Extracted content"}}}},
                "/v1/browser/cdp/stealth/shot": {"post": {"summary": "Stealth screenshot via CDP", "tags": ["CDP Stealth"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"url": {"type": "string"}, "width": {"type": "integer", "default": 1280}, "height": {"type": "integer", "default": 720}, "full_page": {"type": "boolean", "default": False}, "format": {"type": "string", "enum": ["png", "jpeg"], "default": "png"}, "timeout": {"type": "number", "default": 15}}}}}}, "responses": {"200": {"description": "Screenshot data"}}}},
                "/v1/browser/cdp/raw-info": {"get": {"summary": "Raw CDP HTTP info", "tags": ["CDP Debug"], "responses": {"200": {"description": "Raw CDP data"}}}},
                "/v1/browser/cdp/test-launch": {"get": {"summary": "Test CDP browser launch", "tags": ["CDP Debug"], "responses": {"200": {"description": "Launch test result"}}}},
                "/v1/browser/cdp/test-ws": {"get": {"summary": "Test CDP WebSocket", "tags": ["CDP Debug"], "responses": {"200": {"description": "WS test result"}}}},
                "/v1/desktop/screenshot": {"get": {"summary": "Take desktop screenshot", "tags": ["Desktop"], "parameters": [
                    {"name": "format", "in": "query", "schema": {"type": "string", "enum": ["base64", "png", "jpeg", "jpg", "webp"], "default": "base64"}},
                    {"name": "scale", "in": "query", "schema": {"type": "number", "minimum": 0, "maximum": 1}},
                    {"name": "max_width", "in": "query", "schema": {"type": "integer", "minimum": 1}},
                    {"name": "quality", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 80}}
                ], "responses": {"200": {"description": "Screenshot image bytes or base64 JSON"}}}},
                "/v1/desktop/type": {"post": {"summary": "Type text on the desktop", "tags": ["Desktop"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"text": {"type": "string"}, "delay": {"type": "integer", "default": 50}, "clear": {"type": "boolean", "default": False}, "ensure_latin": {"type": "boolean", "default": True}}, "required": ["text"]}}}}, "responses": {"200": {"description": "Type result"}}}},
                "/v1/exec": {"post": {"summary": "Execute command", "tags": ["Exec"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"cmd": {"type": "string"}, "timeout": {"type": "integer", "default": 30}, "cwd": {"type": "string"}}}}}}, "responses": {"200": {"description": "Command result"}}}},
                "/v1/kill": {"post": {"summary": "Kill process by PID", "tags": ["Exec"], "responses": {"200": {"description": "Kill result"}}}},
                "/v1/skills": {"get": {"summary": "List available skills", "tags": ["Skills"], "responses": {"200": {"description": "Skill list"}}}},
                "/v1/skills/run": {"post": {"summary": "Execute a skill", "tags": ["Skills"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"name": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}}}}}}}}, "responses": {"200": {"description": "Skill output"}}},
                "/v1/tasks": {"get": {"summary": "List tasks", "tags": ["Tasks"], "responses": {"200": {"description": "Task list"}}}, "post": {"summary": "Create task (cmd or title)", "tags": ["Tasks"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"cmd": {"type": "string", "description": "Command to execute"}, "title": {"type": "string", "description": "Task title (if no cmd)"}, "description": {"type": "string"}, "priority": {"type": "string", "enum": ["low", "normal", "high"]}}}}}}, "responses": {"200": {"description": "Created task"}}}},
                "/v1/memory": {"get": {"summary": "List memory facts", "tags": ["Memory"], "responses": {"200": {"description": "Memory entries"}}}},
                "/v1/recall": {"get": {"summary": "Recall relevant facts", "tags": ["Memory"], "responses": {"200": {"description": "Recalled facts"}}}},
                "/v1/sysinfo": {"get": {"summary": "System information", "tags": ["System"], "responses": {"200": {"description": "System info"}}}},
                "/v1/audit": {"get": {"summary": "Audit log", "tags": ["System"], "responses": {"200": {"description": "Audit entries"}}}},
                "/v1/doctor": {"get": {"summary": "Run diagnostics", "tags": ["System"], "responses": {"200": {"description": "Diagnostic results"}}}},
                "/gui": {"get": {"summary": "Web dashboard", "tags": ["Bridge"], "responses": {"200": {"description": "HTML dashboard"}}}},
                "/api-docs": {"get": {"summary": "OpenAPI specification", "tags": ["Bridge"], "responses": {"200": {"description": "OpenAPI 3.0 JSON"}}}},
                "/openapi.json": {"get": {"summary": "OpenAPI specification alias", "tags": ["Bridge"], "responses": {"200": {"description": "OpenAPI 3.0 JSON"}}}},
                "/v1/events": {"get": {"summary": "WebSocket real-time event stream", "tags": ["Events"], "responses": {"200": {"description": "WebSocket upgrade for events"}}}},
                "/v1/skills/reload": {"post": {"summary": "Force reload skills cache", "tags": ["Skills"], "responses": {"200": {"description": "Reloaded skills"}}}},
                "/v1/audit/log": {"get": {"summary": "Request/response log with filters", "tags": ["System"], "responses": {"200": {"description": "Request log entries"}}}},
                "/v1/watchdog": {"get": {"summary": "Watchdog status and config", "tags": ["Watchdog"], "responses": {"200": {"description": "Watchdog info"}}}},
                "/v1/users": {"get": {"summary": "List users (admin)", "tags": ["Auth"], "responses": {"200": {"description": "User list"}}}},
                "/v1/batch": {"post": {"summary": "Execute multiple operations in parallel", "tags": ["Bridge"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"operations": {"type": "array", "items": {"type": "object", "properties": {"method": {"type": "string"}, "path": {"type": "string"}, "body": {"type": "object"}}}}, "max_concurrent": {"type": "integer", "default": 5}}}}}}, "responses": {"200": {"description": "Batch results"}}}},
                "/v1/profiles": {"get": {"summary": "List browser session profiles", "tags": ["Profiles"], "responses": {"200": {"description": "Profile list"}}}},
                "/v1/alerts": {"get": {"summary": "Alert configurations and status", "tags": ["Watchdog"], "responses": {"200": {"description": "Alert states"}}}},
            },
            "tags": [
                {"name": "Bridge", "description": "Core bridge operations"},
                {"name": "CDP", "description": "Chrome DevTools Protocol browser control"},
                {"name": "CDP Stealth", "description": "Stealth-aware content extraction and screenshots via CDP"},
                {"name": "CDP Debug", "description": "CDP diagnostic and testing endpoints"},
                {"name": "Exec", "description": "Command execution"},
                {"name": "Desktop", "description": "Desktop screenshot, input, focus and control lease"},
                {"name": "Skills", "description": "Skill system"},
                {"name": "Tasks", "description": "Task management"},
                {"name": "Memory", "description": "Memory and recall"},
                {"name": "System", "description": "System information and diagnostics"},
                {"name": "Events", "description": "Real-time WebSocket event stream"},
                {"name": "Watchdog", "description": "Health monitoring and alerting"},
                {"name": "Auth", "description": "Multi-user authentication and roles"},
                {"name": "Profiles", "description": "Browser session profiles (cookies, tabs, localStorage)"},
            ],
        }
        return ctx.cors_json_response(spec)
    return PublicHandlers(index=handle_index, health=handle_health, api_docs=handle_api_docs)

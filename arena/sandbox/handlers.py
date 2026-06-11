"""Handlers for sandbox execution/configuration endpoints."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import SandboxHandlerContext
from arena.sandbox.runtime import SANDBOX_CONFIG


@dataclass(frozen=True)
class SandboxHandlers:
    sandbox: object


def make_sandbox_handlers(ctx: SandboxHandlerContext) -> SandboxHandlers:
    async def handle_v1_sandbox(request: web.Request) -> web.Response:
        """GET /v1/sandbox — Sandbox configuration.
        POST /v1/sandbox — Run a command in sandbox OR update sandbox config.

        To run: {"action": "run", "cmd": "...", "timeout": 30}
        To configure: {"action": "config", "max_cpu_seconds": 60, ...}
        """
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        if request.method == "GET":
            return ctx.cors_json_response({"ok": True, "config": SANDBOX_CONFIG})

        try:
            data = await request.json()
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)

        action = data.get("action", "run")

        if action == "config":
            # Update configuration.
            for key in ("max_cpu_seconds", "max_memory_mb", "max_output_bytes"):
                if key in data:
                    SANDBOX_CONFIG[key] = int(data[key])
            if "allowed_commands" in data:
                SANDBOX_CONFIG["allowed_commands"] = list(data["allowed_commands"])
            if "blocked_env_vars" in data:
                SANDBOX_CONFIG["blocked_env_vars"] = list(data["blocked_env_vars"])
            if "enabled" in data:
                SANDBOX_CONFIG["enabled"] = bool(data["enabled"])

            ctx.audit({"type": "sandbox_config", "changes": {k: v for k, v in data.items() if k != "action"}})
            return ctx.cors_json_response({"ok": True, "config": SANDBOX_CONFIG})

        if action == "run":
            if not SANDBOX_CONFIG["enabled"]:
                return ctx.cors_json_response({"ok": False, "error": "sandbox is disabled"}, status=403)

            cmd = data.get("cmd", "")
            if not cmd:
                return ctx.cors_json_response({"ok": False, "error": "cmd is required"}, status=400)

            # Check if the command is allowed.
            first_cmd = ctx.first_word(cmd)
            allowed = SANDBOX_CONFIG["allowed_commands"]
            if allowed and first_cmd not in allowed:
                return ctx.cors_json_response({
                    "ok": False,
                    "error": f"command '{first_cmd}' not in allowed list",
                    "allowed": allowed,
                }, status=403)

            # Check for destructive patterns.
            block_reason = ctx.blocked_reason(cmd)
            if block_reason:
                return ctx.cors_json_response({"ok": False, "error": block_reason}, status=403)

            timeout = min(int(data.get("timeout", 30)), SANDBOX_CONFIG["max_cpu_seconds"])
            result = await ctx.run_sandboxed(cmd, timeout=timeout)

            ctx.audit({"type": "sandbox_run", "cmd_len": len(cmd),
                       "exit_code": result.get("exit_code"), "timed_out": result.get("timed_out", False)})
            await ctx.emit_event("sandbox_run", {"cmd": cmd[:50], "ok": result["ok"],
                                                  "exit_code": result.get("exit_code")})

            return ctx.cors_json_response(result)

        return ctx.cors_json_response({"ok": False, "error": "action must be 'run' or 'config'"}, status=400)

    return SandboxHandlers(sandbox=handle_v1_sandbox)

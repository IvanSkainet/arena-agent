"""API v2 exec handler."""
from __future__ import annotations

import asyncio

from aiohttp import web

from arena.api_v2.common import auth_and_record
from arena.handler_context import ApiV2HandlerContext


async def run_unsandboxed_exec(ctx: ApiV2HandlerContext, request: web.Request, cmd: str, data: dict) -> dict:
    timeout = min(int(data.get("timeout", 60)), ctx.cfg_get_max_timeout(request))
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": ctx.decode_output(stdout)[-50000:],
            "stderr": ctx.decode_output(stderr)[-10000:],
            "sandbox": False,
            "api_version": "2",
        }
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"timeout after {timeout}s", "sandbox": False, "api_version": "2"}
    except Exception as e:
        return {"ok": False, "error": str(e), "sandbox": False, "api_version": "2"}


async def run_sandboxed_exec(ctx: ApiV2HandlerContext, cmd: str, data: dict) -> dict:
    first_cmd = ctx.first_word(cmd)
    allowed = ctx.sandbox_config["allowed_commands"]
    if allowed and first_cmd not in allowed:
        return {
            "ok": False,
            "error": f"command '{first_cmd}' not in allowed list (sandbox mode)",
            "allowed": allowed,
            "api_version": "2",
            "_status": 403,
        }
    timeout = min(int(data.get("timeout", 30)), ctx.sandbox_config["max_cpu_seconds"])
    result = await ctx.run_sandboxed(cmd, timeout=timeout)
    result["sandbox"] = True
    result["api_version"] = "2"
    return result


def make_v2_exec_handler(ctx: ApiV2HandlerContext):
    async def handle_v2_exec(request: web.Request) -> web.Response:
        """POST /v2/exec — Execute command in sandbox by default."""
        response = auth_and_record(ctx, request)
        if response:
            return response

        try:
            data = await request.json()
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)

        cmd = data.get("cmd", "")
        if not cmd:
            return ctx.cors_json_response({"ok": False, "error": "missing 'cmd'"}, status=400)

        block = ctx.blocked_reason(cmd)
        if block:
            return ctx.cors_json_response({"ok": False, "error": block}, status=403)

        use_sandbox = data.get("sandbox", True)
        if use_sandbox and ctx.sandbox_config["enabled"]:
            result = await run_sandboxed_exec(ctx, cmd, data)
            status = result.pop("_status", 200)
            if status != 200:
                return ctx.cors_json_response(result, status=status)
        else:
            result = await run_unsandboxed_exec(ctx, request, cmd, data)

        ctx.audit({"type": "exec_v2", "cmd_len": len(cmd), "sandbox": use_sandbox, "exit_code": result.get("exit_code")})
        await ctx.emit_event("exec", {"cmd": cmd[:50], "ok": result["ok"], "sandbox": use_sandbox})
        ctx.record_request(is_exec=True)
        return ctx.cors_json_response(result)

    return handle_v2_exec

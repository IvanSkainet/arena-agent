"""Handlers for exec/process endpoints."""
from __future__ import annotations

import asyncio
import os
import signal
import uuid
from dataclasses import dataclass
from pathlib import Path

from aiohttp import web

from arena.handler_context import ExecHandlerContext

_BLOCKED_ENV_PATTERNS = [
    "ARENA_TOKEN", "TOKEN", "SECRET", "PASSWORD", "KEY",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONSTARTUP",
]


@dataclass(frozen=True)
class ExecHandlers:
    ps: object
    exec: object
    kill: object


def make_exec_handlers(ctx: ExecHandlerContext) -> ExecHandlers:
    async def handle_v1_ps(request: web.Request) -> web.Response:
        try:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            ps_list = ctx.active_processes_snapshot(max_cmd_len=200)
            return ctx.cors_json_response({"ok": True, "processes": ps_list, "count": len(ps_list)})
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_exec(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        cfg = request.app["cfg"]

        try:
            data = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)

        if not isinstance(data, dict):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "JSON must be object"}, status=400)

        request_id = str(data.get("request_id") or uuid.uuid4())
        cmd = str(data.get("cmd", "")).strip()
        if not cmd:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing cmd", "request_id": request_id}, status=400)

        reason = ctx.blocked_reason(cmd)
        if reason:
            ctx.audit({"type": "exec_blocked", "request_id": request_id, "cmd": cmd, "reason": reason, "client": request.remote or "127.0.0.1"})
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": reason, "request_id": request_id}, status=403)

        ctrl_err = ctx.control_check()
        if ctrl_err:
            inj = ctx.is_input_injection_cmd(cmd)
            if inj:
                ctx.audit({"type": "exec_blocked_control", "request_id": request_id, "cmd": cmd,
                           "reason": ctrl_err.get("error"), "matched": inj,
                           "client": request.remote or "127.0.0.1"})
                ctx.record_request(is_error=True, count_request=False)
                err = dict(ctrl_err)
                err["request_id"] = request_id
                err["message"] = (
                    "Desktop input injection blocked while control is "
                    f"{ctrl_err.get('status')}. Resume control to inject input."
                )
                return ctx.cors_json_response(err, status=403)

        profile = cfg["profile"]
        first = ctx.first_word(cmd)
        if profile == "cautious" and first not in ctx.cautious_allow:
            reason = f"command '{first}' not in cautious allowlist; use --profile owner-shell"
            ctx.audit({"type": "exec_blocked", "request_id": request_id, "cmd": cmd, "reason": reason, "client": request.remote or "127.0.0.1"})
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": reason, "request_id": request_id}, status=403)

        root: Path = cfg["root"]
        cwd_raw = str(data.get("cwd") or root)
        cwd = Path(cwd_raw).expanduser()
        if not cwd.is_absolute():
            cwd = root / cwd
        if not cfg["allow_any_cwd"] and not ctx.under_root(cwd, root):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"cwd must be under root {root}", "request_id": request_id}, status=403)
        if not cwd.exists() or not cwd.is_dir():
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"cwd does not exist: {cwd}", "request_id": request_id}, status=400)

        timeout = min(int(data.get("timeout", cfg["timeout"])), cfg["max_timeout"])
        max_output = min(int(data.get("max_output", ctx.default_max_output)), cfg["max_output"])
        env_extra = data.get("env") if isinstance(data.get("env"), dict) else {}
        env = os.environ.copy()
        for key in list(env_extra.keys()):
            for blocked in _BLOCKED_ENV_PATTERNS:
                if blocked in key.upper():
                    del env_extra[key]
                    break
        env.update({str(k): str(v) for k, v in env_extra.items()})

        sem: asyncio.Semaphore = cfg["semaphore"]
        if sem.locked() and cfg["active_exec"] >= cfg["max_concurrent"]:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "too many concurrent exec requests", "request_id": request_id}, status=429)

        await sem.acquire()
        cfg["active_exec"] += 1
        ctx.audit({"type": "exec_start", "request_id": request_id, "cmd": cmd, "cwd": str(cwd), "timeout": timeout, "client": request.remote or "127.0.0.1"})

        try:
            result = await ctx.run_shell_command(
                request_id=request_id,
                cmd=cmd,
                cwd=cwd,
                env=env,
                timeout=timeout,
                max_output=max_output,
                decode_output_fn=ctx.decode_output,
            )
            event_type = "exec_timeout" if result.get("timed_out") else "exec_done"
            ctx.audit({"type": event_type, "request_id": request_id, "cmd": cmd, "exit_code": result.get("exit_code"),
                       "duration": result.get("duration_sec"), "truncated": result.get("truncated"),
                       "stdout_bytes": result.get("stdout_bytes"), "stderr_bytes": result.get("stderr_bytes")})
            ctx.record_request(duration=result.get("duration_sec", 0.0), is_exec=True, is_error=not result.get("ok"))
            response = dict(result)
            response.pop("timed_out", None)
            return ctx.cors_json_response(response, status=408 if result.get("timed_out") else 200)
        except Exception as e:
            duration = 0.0
            ctx.audit({"type": "exec_error", "request_id": request_id, "cmd": cmd, "duration": duration, "error": repr(e)})
            ctx.record_request(duration=duration, is_exec=True, is_error=True)
            return ctx.cors_json_response({"ok": False, "request_id": request_id, "error": "Internal error", "duration_sec": duration}, status=500)
        finally:
            cfg["active_exec"] -= 1
            sem.release()

    async def handle_v1_kill(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        try:
            data = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "invalid json"}, status=400)
        target_id = data.get("request_id")
        if not target_id or target_id not in ctx.active_processes:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "process not found"}, status=404)
        info = ctx.active_processes[target_id]
        try:
            os.kill(info["pid"], signal.SIGTERM if os.name != "nt" else signal.CTRL_BREAK_EVENT)
        except Exception:
            pass
        ctx.audit({"type": "process_killed", "target_request_id": target_id, "client": request.remote or "127.0.0.1"})
        ctx.record_request()
        return ctx.cors_json_response({"ok": True, "killed": target_id})

    return ExecHandlers(ps=handle_v1_ps, exec=handle_v1_exec, kill=handle_v1_kill)

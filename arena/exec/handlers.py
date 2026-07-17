"""Handlers for exec/process endpoints.

v3.94.0: Migrated to @authed / err_json / parse_json_body helpers
from arena.handler_helpers. Auth preludes and error-response
scaffolding centralized; exec handler keeps its own request
accounting (duration + is_exec) via ``auto_record=False``.

v4.2.0: Added POST /v1/exec/script — raw script body execution
so agents don't have to double-JSON-encode multi-line scripts or
upload-then-exec them as a temp file dance. Interpreter picked
via ``X-Arena-Interpreter`` header (default: bash on POSIX,
powershell on Windows). Body-shape decision: text/plain body =
script, JSON body = preserve legacy /v1/exec compat.

v4.3.0: Added POST /v1/exec/stream — chunked NDJSON streaming
endpoint that emits one JSON event per line
(``start`` → ``stdout``/``stderr`` chunks → ``exit``) as soon as
bytes arrive from the child process. Same auth / blocklist /
control-lease / profile / cwd / semaphore / audit gates as
/v1/exec so agents can watch ``pytest`` or ``docker pull`` live
instead of blocking on the full response.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from aiohttp import web
from arena.app_keys import APP_CFG

from arena.exec.runner import run_shell_command_stream
from arena.handler_context import ExecHandlerContext
from arena.handler_helpers import authed, err_json, parse_json_body
from arena.http import CORS_HEADERS

_BLOCKED_ENV_PATTERNS = [
    "ARENA_TOKEN", "TOKEN", "SECRET", "PASSWORD", "KEY",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONSTARTUP",
]

# v4.2.0: interpreter → (cmdline template, filename suffix, unix?)
# The template takes ``{path}`` for the temp script path; the shell
# quoting is single-arg because we execute via create_subprocess_exec-
# equivalent through the existing run_shell_command shim, which uses
# shell mode. Interpreters that need special flags (bash -euo pipefail)
# are configured here so agents don't have to think about it.
_INTERPRETERS: dict[str, dict[str, object]] = {
    "bash":       {"cmd": "bash -euo pipefail {path}",        "suffix": ".sh",   "unix": True},
    "sh":         {"cmd": "sh -eu {path}",                     "suffix": ".sh",   "unix": True},
    "python":     {"cmd": "python3 {path}",                    "suffix": ".py",   "unix": True},
    "python3":    {"cmd": "python3 {path}",                    "suffix": ".py",   "unix": True},
    "node":       {"cmd": "node {path}",                       "suffix": ".js",   "unix": True},
    "pwsh":       {"cmd": "pwsh -NoProfile -File {path}",      "suffix": ".ps1",  "unix": False},
    "powershell": {"cmd": "powershell -NoProfile -File {path}","suffix": ".ps1",  "unix": False},
}

_DEFAULT_INTERPRETER_UNIX = "bash"
_DEFAULT_INTERPRETER_WIN = "powershell"


@dataclass(frozen=True)
class ExecHandlers:
    ps: object
    exec: object
    kill: object
    # v4.2.0: raw-script endpoint.
    script: object
    # v4.3.0: NDJSON streaming endpoint.
    stream: object


def _resolve_interpreter(name: str) -> tuple[str, dict[str, object]] | None:
    """Return (name, config) for a supported interpreter or None.
    Falls back to platform default when name is empty."""
    if not name:
        name = _DEFAULT_INTERPRETER_WIN if os.name == "nt" else _DEFAULT_INTERPRETER_UNIX
    lower = name.strip().lower()
    if lower in _INTERPRETERS:
        return lower, _INTERPRETERS[lower]
    return None


def _which_interpreter(cmdline_template: str) -> str | None:
    """Return the resolved absolute path of the interpreter binary,
    or None if it's not on PATH. Used so a 404-style 'bash not
    installed' comes back as a clear 400, not a shell error."""
    first = cmdline_template.split()[0]
    return shutil.which(first)


def make_exec_handlers(ctx: ExecHandlerContext) -> ExecHandlers:
    @authed(ctx)
    async def handle_v1_ps(request: web.Request) -> web.Response:
        ps_list = ctx.active_processes_snapshot(max_cmd_len=200)
        return ctx.cors_json_response({"ok": True, "processes": ps_list, "count": len(ps_list)})

    @authed(ctx, auto_record=False)
    async def handle_v1_exec(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]

        data, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            ctx.record_request(is_error=True, count_request=False)
            return jerr

        request_id = str(data.get("request_id") or uuid.uuid4())
        cmd = str(data.get("cmd", "")).strip()
        if not cmd:
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, "missing cmd", status=400, request_id=request_id)

        reason = ctx.blocked_reason(cmd)
        if reason:
            ctx.audit({"type": "exec_blocked", "request_id": request_id, "cmd": cmd,
                       "reason": reason, "client": request.remote or "127.0.0.1"})
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, reason, status=403, request_id=request_id)

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
            ctx.audit({"type": "exec_blocked", "request_id": request_id, "cmd": cmd,
                       "reason": reason, "client": request.remote or "127.0.0.1"})
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, reason, status=403, request_id=request_id)

        root: Path = cfg["root"]
        cwd_raw = str(data.get("cwd") or root)
        cwd = Path(cwd_raw).expanduser()
        if not cwd.is_absolute():
            cwd = root / cwd
        if not cfg["allow_any_cwd"] and not ctx.under_root(cwd, root):
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, f"cwd must be under root {root}", status=403, request_id=request_id)
        if not cwd.exists() or not cwd.is_dir():
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, f"cwd does not exist: {cwd}", status=400, request_id=request_id)

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
            return err_json(ctx, "too many concurrent exec requests",
                            status=429, request_id=request_id)

        await sem.acquire()
        cfg["active_exec"] += 1
        ctx.audit({"type": "exec_start", "request_id": request_id, "cmd": cmd, "cwd": str(cwd),
                   "timeout": timeout, "client": request.remote or "127.0.0.1"})

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
            ctx.audit({"type": event_type, "request_id": request_id, "cmd": cmd,
                       "exit_code": result.get("exit_code"),
                       "duration": result.get("duration_sec"),
                       "truncated": result.get("truncated"),
                       "stdout_bytes": result.get("stdout_bytes"),
                       "stderr_bytes": result.get("stderr_bytes")})
            ctx.record_request(duration=result.get("duration_sec", 0.0),
                               is_exec=True, is_error=not result.get("ok"))
            response = dict(result)
            response.pop("timed_out", None)
            return ctx.cors_json_response(response, status=408 if result.get("timed_out") else 200)
        except Exception as e:
            duration = 0.0
            ctx.audit({"type": "exec_error", "request_id": request_id, "cmd": cmd,
                       "duration": duration, "error": repr(e)})
            ctx.record_request(duration=duration, is_exec=True, is_error=True)
            return ctx.cors_json_response(
                {"ok": False, "request_id": request_id,
                 "error": "Internal error", "duration_sec": duration},
                status=500,
            )
        finally:
            cfg["active_exec"] -= 1
            sem.release()

    # v4.2.0 raw-script endpoint. Same auth + profile + control gates as
    # /v1/exec, but body-shape is raw script bytes and interpreter comes
    # from a header. Removes the need for agents to double-JSON-encode
    # multi-line bash / python and then read stdout back through a
    # nested string.
    @authed(ctx, auto_record=False)
    async def handle_v1_exec_script(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        request_id = str(request.headers.get("X-Arena-Request-Id") or uuid.uuid4())

        # Read the raw script body. Cap defensively at 5 MiB — anything
        # bigger should upload via /v1/upload + exec.
        body = await request.read()
        if not body:
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, "empty script body", status=400, request_id=request_id)
        max_script = 5 * 1024 * 1024
        if len(body) > max_script:
            ctx.record_request(is_error=True, count_request=False)
            return err_json(
                ctx,
                f"script body too large: {len(body)} bytes; cap is {max_script}",
                status=413, request_id=request_id,
            )

        # Interpreter selection.
        interp_name = request.headers.get("X-Arena-Interpreter", "").strip()
        resolved = _resolve_interpreter(interp_name)
        if resolved is None:
            ctx.record_request(is_error=True, count_request=False)
            return err_json(
                ctx,
                f"unsupported interpreter {interp_name!r}. Supported: "
                + ", ".join(sorted(_INTERPRETERS.keys())),
                status=400, request_id=request_id,
            )
        interp_key, interp_cfg = resolved

        # Refuse to run a Unix-only interpreter on Windows and vice-versa
        # so a clear 400 comes back instead of a mysterious shell error.
        if os.name == "nt" and interp_cfg["unix"]:
            ctx.record_request(is_error=True, count_request=False)
            return err_json(
                ctx, f"interpreter {interp_key!r} not available on Windows",
                status=400, request_id=request_id,
            )
        if os.name != "nt" and not interp_cfg["unix"]:
            ctx.record_request(is_error=True, count_request=False)
            return err_json(
                ctx, f"interpreter {interp_key!r} not available on this OS",
                status=400, request_id=request_id,
            )

        if not _which_interpreter(str(interp_cfg["cmd"])):
            ctx.record_request(is_error=True, count_request=False)
            return err_json(
                ctx, f"interpreter {interp_key!r} not installed / not on PATH",
                status=400, request_id=request_id,
            )

        # Timeout / cwd via headers (fall back to cfg defaults).
        try:
            timeout = min(int(request.headers.get("X-Arena-Timeout", cfg["timeout"])),
                          cfg["max_timeout"])
        except (TypeError, ValueError):
            timeout = int(cfg["timeout"])
        max_output = int(cfg["max_output"])

        root: Path = cfg["root"]
        cwd_hdr = (request.headers.get("X-Arena-Cwd") or "").strip()
        cwd = Path(cwd_hdr).expanduser() if cwd_hdr else root
        if not cwd.is_absolute():
            cwd = root / cwd
        if not cfg["allow_any_cwd"] and not ctx.under_root(cwd, root):
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, f"cwd must be under root {root}",
                            status=403, request_id=request_id)
        if not cwd.exists() or not cwd.is_dir():
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, f"cwd does not exist: {cwd}",
                            status=400, request_id=request_id)

        # Concurrency gate: same semaphore as /v1/exec so the two
        # endpoints share fairness rather than doubling capacity.
        sem: asyncio.Semaphore = cfg["semaphore"]
        if sem.locked() and cfg["active_exec"] >= cfg["max_concurrent"]:
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, "too many concurrent exec requests",
                            status=429, request_id=request_id)

        # Write body to a tmpfile scoped to root so cross-mount deletes
        # can't leak. mkstemp is race-free and gives us a mode 0o600 file.
        tmp_dir = root / ".arena_script_tmp"
        tmp_dir.mkdir(exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=f"scr-{request_id[:8]}-",
                                        suffix=str(interp_cfg["suffix"]),
                                        dir=str(tmp_dir))
        os.close(fd)
        try:
            Path(tmp_path).write_bytes(body)
            # Make the script executable so `sh <path>` works even when
            # umask is unusually restrictive.
            try:
                os.chmod(tmp_path, 0o700)  # nosemgrep: insecure-file-permissions -- 0o700 is owner-only rwx; the script needs exec bit to run via `sh <path>` and no other user should read/execute it (see mkstemp above which already produced 0o600)
            except Exception:
                pass

            full_cmd = str(interp_cfg["cmd"]).format(path=tmp_path)

            # Same blocklist that /v1/exec uses — but applied to the
            # interpreter cmdline, not the script body. Script bodies
            # are opaque to the blocklist; if you want to restrict what
            # the script itself can do, use a --profile.
            reason = ctx.blocked_reason(full_cmd)
            if reason:
                ctx.audit({"type": "exec_script_blocked", "request_id": request_id,
                           "interpreter": interp_key, "reason": reason,
                           "client": request.remote or "127.0.0.1"})
                ctx.record_request(is_error=True, count_request=False)
                return err_json(ctx, reason, status=403, request_id=request_id)

            env = os.environ.copy()

            await sem.acquire()
            cfg["active_exec"] += 1
            ctx.audit({"type": "exec_script_start", "request_id": request_id,
                       "interpreter": interp_key, "bytes": len(body),
                       "cwd": str(cwd), "timeout": timeout,
                       "client": request.remote or "127.0.0.1"})
            try:
                result = await ctx.run_shell_command(
                    request_id=request_id,
                    cmd=full_cmd,
                    cwd=cwd,
                    env=env,
                    timeout=timeout,
                    max_output=max_output,
                    decode_output_fn=ctx.decode_output,
                )
                event_type = "exec_script_timeout" if result.get("timed_out") else "exec_script_done"
                ctx.audit({"type": event_type, "request_id": request_id,
                           "interpreter": interp_key,
                           "exit_code": result.get("exit_code"),
                           "duration": result.get("duration_sec"),
                           "truncated": result.get("truncated"),
                           "stdout_bytes": result.get("stdout_bytes"),
                           "stderr_bytes": result.get("stderr_bytes")})
                ctx.record_request(duration=result.get("duration_sec", 0.0),
                                   is_exec=True, is_error=not result.get("ok"))
                response = dict(result)
                response.pop("timed_out", None)
                response["interpreter"] = interp_key
                response["script_bytes"] = len(body)
                return ctx.cors_json_response(
                    response,
                    status=408 if result.get("timed_out") else 200,
                )
            except Exception as e:  # noqa: BLE001
                ctx.audit({"type": "exec_script_error", "request_id": request_id,
                           "interpreter": interp_key, "error": repr(e)})
                ctx.record_request(duration=0.0, is_exec=True, is_error=True)
                return ctx.cors_json_response(
                    {"ok": False, "request_id": request_id,
                     "error": "Internal error", "duration_sec": 0.0,
                     "interpreter": interp_key},
                    status=500,
                )
            finally:
                cfg["active_exec"] -= 1
                sem.release()
        finally:
            # Delete the tmp script even on error — no lingering
            # bytes on disk. Ignore ENOENT if we never wrote it.
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            except Exception:
                pass

    # v4.3.0 NDJSON streaming endpoint. Same auth + gates as /v1/exec, but
    # emits one JSON event per line as bytes arrive from the child process
    # so agents can watch long-running commands (pytest, docker pull, npm
    # build, ...) live instead of blocking on the full response.
    @authed(ctx, auto_record=False)
    async def handle_v1_exec_stream(request: web.Request) -> web.StreamResponse:
        cfg = request.app[APP_CFG]

        data, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            ctx.record_request(is_error=True, count_request=False)
            return jerr

        request_id = str(data.get("request_id") or uuid.uuid4())
        cmd = str(data.get("cmd", "")).strip()
        if not cmd:
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, "missing cmd", status=400, request_id=request_id)

        reason = ctx.blocked_reason(cmd)
        if reason:
            ctx.audit({"type": "exec_stream_blocked", "request_id": request_id, "cmd": cmd,
                       "reason": reason, "client": request.remote or "127.0.0.1"})
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, reason, status=403, request_id=request_id)

        ctrl_err = ctx.control_check()
        if ctrl_err:
            inj = ctx.is_input_injection_cmd(cmd)
            if inj:
                ctx.audit({"type": "exec_stream_blocked_control", "request_id": request_id,
                           "cmd": cmd, "reason": ctrl_err.get("error"), "matched": inj,
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
            ctx.audit({"type": "exec_stream_blocked", "request_id": request_id, "cmd": cmd,
                       "reason": reason, "client": request.remote or "127.0.0.1"})
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, reason, status=403, request_id=request_id)

        root: Path = cfg["root"]
        cwd_raw = str(data.get("cwd") or root)
        cwd = Path(cwd_raw).expanduser()
        if not cwd.is_absolute():
            cwd = root / cwd
        if not cfg["allow_any_cwd"] and not ctx.under_root(cwd, root):
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, f"cwd must be under root {root}", status=403, request_id=request_id)
        if not cwd.exists() or not cwd.is_dir():
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, f"cwd does not exist: {cwd}", status=400, request_id=request_id)

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
            return err_json(ctx, "too many concurrent exec requests",
                            status=429, request_id=request_id)

        # NDJSON stream: chunked transfer, one JSON object per line. Setting
        # X-Accel-Buffering: no is a hint for reverse proxies (nginx) to not
        # coalesce chunks — matters when the bridge sits behind a Tailscale
        # funnel or similar. The response itself is unbuffered from aiohttp.
        headers = dict(CORS_HEADERS)
        headers["Content-Type"] = "application/x-ndjson"
        headers["Cache-Control"] = "no-cache"
        headers["X-Accel-Buffering"] = "no"
        headers["X-Arena-Request-Id"] = request_id
        response = web.StreamResponse(status=200, headers=headers)
        response.enable_chunked_encoding()
        await response.prepare(request)

        async def _emit(event: dict) -> None:
            line = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
            await response.write(line)

        await sem.acquire()
        cfg["active_exec"] += 1
        ctx.audit({"type": "exec_stream_start", "request_id": request_id, "cmd": cmd,
                   "cwd": str(cwd), "timeout": timeout,
                   "client": request.remote or "127.0.0.1"})
        # Header event with request_id — the runner will emit "start" once
        # the pid is known. Two events is worth it: clients often want to
        # tag the whole stream by request_id before the child even spawns.
        await _emit({"type": "meta", "request_id": request_id,
                     "cmd": cmd, "cwd": str(cwd), "timeout": timeout})

        exit_event: dict | None = None
        try:
            async for ev in run_shell_command_stream(
                request_id=request_id,
                cmd=cmd,
                cwd=cwd,
                env=env,
                timeout=timeout,
                max_output=max_output,
            ):
                if ev["type"] in ("stdout", "stderr"):
                    # Decode with the bridge's usual decoder so multi-byte
                    # UTF-8 that spans chunk boundaries is best-effort
                    # handled by the same replace policy /v1/exec uses.
                    payload = ctx.decode_output(ev["data"])
                    await _emit({"type": ev["type"], "data": payload,
                                 "bytes": len(ev["data"])})
                elif ev["type"] == "start":
                    await _emit({"type": "start", "pid": ev.get("pid"),
                                 "request_id": request_id})
                elif ev["type"] == "exit":
                    exit_event = dict(ev)
                    exit_event["request_id"] = request_id
                    await _emit(exit_event)
                else:
                    await _emit(ev)

            duration = float(exit_event.get("duration_sec", 0.0)) if exit_event else 0.0
            timed_out = bool(exit_event.get("timed_out")) if exit_event else False
            exit_code = exit_event.get("exit_code") if exit_event else None
            event_type = "exec_stream_timeout" if timed_out else "exec_stream_done"
            ctx.audit({"type": event_type, "request_id": request_id, "cmd": cmd,
                       "exit_code": exit_code, "duration": duration,
                       "truncated": bool(exit_event.get("truncated")) if exit_event else False,
                       "stdout_bytes": exit_event.get("stdout_bytes") if exit_event else 0,
                       "stderr_bytes": exit_event.get("stderr_bytes") if exit_event else 0})
            ctx.record_request(duration=duration, is_exec=True,
                               is_error=timed_out or (exit_code != 0))
        except Exception as e:  # noqa: BLE001
            ctx.audit({"type": "exec_stream_error", "request_id": request_id,
                       "cmd": cmd, "error": repr(e)})
            ctx.record_request(duration=0.0, is_exec=True, is_error=True)
            # Best-effort tail-event so the client sees a terminal marker
            # even after an internal error.
            try:
                await _emit({"type": "error", "request_id": request_id,
                             "error": "Internal error"})
            except Exception:
                pass
        finally:
            cfg["active_exec"] -= 1
            sem.release()
            try:
                await response.write_eof()
            except Exception:
                pass
        return response

    @authed(ctx, auto_record=False)
    async def handle_v1_kill(request: web.Request) -> web.Response:
        data, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            ctx.record_request(is_error=True, count_request=False)
            return jerr
        target_id = data.get("request_id")
        if not target_id or target_id not in ctx.active_processes:
            ctx.record_request(is_error=True, count_request=False)
            return err_json(ctx, "process not found", status=404)
        info = ctx.active_processes[target_id]
        try:
            os.kill(info["pid"], signal.SIGTERM if os.name != "nt" else signal.CTRL_BREAK_EVENT)
        except Exception:
            pass
        ctx.audit({"type": "process_killed", "target_request_id": target_id,
                   "client": request.remote or "127.0.0.1"})
        ctx.record_request()
        return ctx.cors_json_response({"ok": True, "killed": target_id})

    return ExecHandlers(
        ps=handle_v1_ps,
        exec=handle_v1_exec,
        kill=handle_v1_kill,
        script=handle_v1_exec_script,
        stream=handle_v1_exec_stream,
    )

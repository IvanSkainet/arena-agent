"""BrowserAct backend for the high-level browser browse endpoint."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from arena.handler_context import BrowserBrowseHandlerContext


def _browseract_likely_cause(error_name: str | None, error: str, error_data: dict | None) -> tuple[str | None, str | None]:
    if error_name in {"CLI_AUTH_REQUIRED", "AUTH_REQUIRED"}:
        return ("browseract_api_key_missing",
                "Run set_browseract_api_key.bat or `python skills/browseract/run.py auth set <API_KEY>` locally.")
    if error_name in {"CONNECTION_FAILED", "COMMAND_EXECUTION_FAILED"} and "WebSocket URL" in (error or ""):
        cdp = (error_data or {}).get("cdp_url")
        detail = f" BrowserAct reported cdp_url={cdp}." if cdp else ""
        return ("browseract_local_cdp_proxy_failed",
                "BrowserAct auth and browser list may be OK, but its local CDP proxy did not expose /json/version." + detail +
                " Try BrowserAct daemon restart/report-log or run the interactive BrowserAct test from the desktop session.")
    return (None, None)


def _browseract_error_response(ctx: BrowserBrowseHandlerContext, stderr: str, rc: int):
    raw = (stderr or "").strip()
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        err = str(parsed.get("error") or "")
        error_name = parsed.get("error_name")
        error_data = parsed.get("error_data") if isinstance(parsed.get("error_data"), dict) else None
        likely, next_action = _browseract_likely_cause(error_name, err, error_data)
        payload = {
            "ok": False,
            "backend": "browseract",
            "error": err,
            "error_code": parsed.get("error_code"),
            "error_name": error_name,
            "error_data": error_data,
            "likely_cause": likely,
            "next_action": next_action,
            "raw_exit_code": rc,
        }
        return ctx.cors_json_response(payload, status=500)
    return ctx.cors_json_response({"ok": False, "backend": "browseract",
                                   "error": f"BrowserAct failed (rc={rc}): {raw[:2000]}",
                                   "raw_exit_code": rc}, status=500)


async def run_browseract_browse(
    ctx: BrowserBrowseHandlerContext,
    *,
    action: str,
    url: str,
    wait_for: str | None,
    timeout: float,
    width: int,
    height: int,
):
    """Execute a /v1/browser/browse request through the BrowserAct skill."""
    try:
        ba_skill = Path(ctx.app_dir) / "skills" / "browseract" / "run.py"
        if not ba_skill.exists():
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "BrowserAct skill not installed"}, status=503)

        # v4.106.0: run the cross-platform Python wrapper directly. The old
        # path used bash + run.sh, which fails on Windows services without Git
        # Bash even though BrowserAct itself is installed and usable.
        cmd = [sys.executable, str(ba_skill), action, url]
        if wait_for:
            cmd.extend(["--wait-for", wait_for])
        if action == "shot":
            cmd.extend(["--width", str(width), "--height", str(height)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 30)

        if proc.returncode == 0 and stdout:
            try:
                result = json.loads(stdout.decode("utf-8", errors="replace"))
                result["backend"] = "browseract"
                result["stealth"] = True
                return ctx.cors_json_response(result)
            except json.JSONDecodeError:
                text = stdout.decode("utf-8", errors="replace")
                return ctx.cors_json_response({
                    "ok": True,
                    "backend": "browseract",
                    "stealth": True,
                    "output": text[:50000],
                })

        err = stderr.decode("utf-8", errors="replace") if stderr else "unknown error"
        ctx.record_request(is_error=True, count_request=False)
        # returncode is None only while the process is still running; we are
        # past `communicate()` here, so -1 stands in for "unknown exit".
        return _browseract_error_response(ctx, err, proc.returncode if proc.returncode is not None else -1)
    except asyncio.TimeoutError:
        ctx.record_request(is_error=True, count_request=False)
        return ctx.cors_json_response({"ok": False, "error": f"BrowserAct timed out ({timeout}s)"}, status=408)
    except Exception as e:
        ctx.record_request(is_error=True, count_request=False)
        return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

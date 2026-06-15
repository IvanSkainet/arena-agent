"""BrowserAct backend for the high-level browser browse endpoint."""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from arena.handler_context import BrowserBrowseHandlerContext


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
        ba_skill = Path(ctx.app_dir) / "skills" / "browseract" / "run.sh"
        if not ba_skill.exists():
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "BrowserAct skill not installed"}, status=503)

        cmd = [shutil.which("bash") or "bash", str(ba_skill), action, url]
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

        err = stderr.decode("utf-8", errors="replace")[:2000] if stderr else "unknown error"
        ctx.record_request(is_error=True, count_request=False)
        return ctx.cors_json_response({"ok": False, "error": f"BrowserAct failed (rc={proc.returncode}): {err}"}, status=500)
    except asyncio.TimeoutError:
        ctx.record_request(is_error=True, count_request=False)
        return ctx.cors_json_response({"ok": False, "error": f"BrowserAct timed out ({timeout}s)"}, status=408)
    except Exception as e:
        ctx.record_request(is_error=True, count_request=False)
        return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

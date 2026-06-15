"""Desktop command execution helper."""
from __future__ import annotations

import asyncio


async def _desktop_exec(cmd: str, timeout: float = 10) -> dict:
    """Run a desktop automation command and return result dict."""
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
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": f"Command timed out ({timeout}s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

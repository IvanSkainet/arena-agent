"""Runtime helpers for the Arena Web Gateway endpoints."""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any

GW_WHITELIST = (
    "agentctl skill ", "agentctl mem ", "agentctl recall ",
    "agentctl sub list", "agentctl sub show", "agentctl sub spawn",
    "agentctl browser py-", "agentctl agents ", "agentctl mission list",
    "agentctl sys status", "agentctl hooks list", "agentctl report ",
)

_BLOCKED_GATEWAY_CHARS = [";", "&", "|", "`", "$", "(", ")", "{", "}", "\n", ">", ">>", "<"]


def gw_allowed(cmd: str) -> bool:
    """Check if a gateway command is allowed. Blocks shell metacharacters."""
    if not any(cmd.startswith(p) for p in GW_WHITELIST):
        return False
    for ch in _BLOCKED_GATEWAY_CHARS:
        if ch in cmd:
            return False
    return True


def gw_run_sync(
    cmd: str,
    timeout: int,
    *,
    subprocess_kwargs: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Synchronous gateway command runner — returns dict result."""
    try:
        p = subprocess.run(
            cmd,
            shell=True,  # nosec B602 -- gateway.run_cmd is fed only by operator-side tooling; HTTP paths go through arena/exec/handler.py which uses argv-form.
            capture_output=True,
            text=True,
            timeout=timeout,
            **subprocess_kwargs(),
        )
        return {
            "ok": p.returncode == 0,
            "exit": p.returncode,
            "stdout": p.stdout[-20000:],
            "stderr": p.stderr[-3000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "exit": -2, "stdout": "", "stderr": str(e)}

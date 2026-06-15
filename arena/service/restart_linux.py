"""Linux restart/respawn helper implementation."""
from __future__ import annotations

import shutil
import subprocess as sp

from arena.service.restart_common import (
    RestartContext,
    launch_detached_shell_script,
    render_template,
    temp_script_path,
    write_script,
)
from arena.util import _subprocess_kwargs


SYSTEMD_RUN_TEMPLATE = r"""
sleep 2
systemctl --user restart arena-bridge.service >/dev/null 2>&1 || true
for i in $(seq 1 20); do
    if curl -fsS http://127.0.0.1:__PORT__/health >/dev/null 2>&1; then
        exit 0
    fi
    sleep 1
done
TOK=""
if [ -f "__TOKEN_FILE__" ]; then
    TOK="$(cat '__TOKEN_FILE__' | tr -d '\n ' )"
fi
nohup python3 -u "__BRIDGE__" serve --root "$HOME" --profile owner-shell ${TOK:+--token "$TOK"} --port __PORT__ >/dev/null 2>&1 &
"""

SH_TEMPLATE = r"""#!/usr/bin/env bash
sleep 2
if command -v systemctl >/dev/null 2>&1 && systemctl --user list-unit-files arena-bridge.service >/dev/null 2>&1; then
    systemctl --user restart arena-bridge.service
fi
for i in $(seq 1 12); do
    if curl -fsS http://127.0.0.1:__PORT__/health >/dev/null 2>&1; then
        rm -f "$0"; exit 0
    fi
    sleep 1
done
TOK=""
[[ -f "__TOKEN_FILE__" ]] && TOK="$(cat '__TOKEN_FILE__' | tr -d '\n ')"
nohup python3 -u "__BRIDGE__" serve --root "$HOME" --profile owner-shell ${TOK:+--token "$TOK"} --port __PORT__ >/dev/null 2>&1 &
disown
rm -f "$0"
"""


def _try_systemd_run(ctx: RestartContext, script: str) -> tuple[bool, str] | None:
    try:
        if not (shutil.which("systemd-run") and shutil.which("systemctl")):
            return None
        unit = f"arena-bridge-restart-{ctx.pid}"
        result = sp.run(
            ["systemd-run", "--user", "--unit", unit, "--collect", "bash", "-lc", script],
            capture_output=True,
            text=True,
            timeout=5,
            **_subprocess_kwargs(),
        )
        if result.returncode == 0:
            return True, f"systemd-run transient unit ({unit})"
    except Exception:
        return None
    return None


def spawn_linux_respawn_helper(ctx: RestartContext) -> tuple[bool, str]:
    systemd_script = render_template(SYSTEMD_RUN_TEMPLATE, ctx)
    systemd_result = _try_systemd_run(ctx, systemd_script)
    if systemd_result:
        return systemd_result

    path = temp_script_path("arena_respawn", ".sh", ctx.pid)
    script = render_template(SH_TEMPLATE, ctx)
    try:
        write_script(path, script, executable=True)
        launch_detached_shell_script(path)
        return True, f"detached .sh fallback (file={path.name})"
    except Exception as e:
        return False, f"spawn failed: {e}"

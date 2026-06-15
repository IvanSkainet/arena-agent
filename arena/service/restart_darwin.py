"""macOS restart/respawn helper implementation."""
from __future__ import annotations

from arena.service.restart_common import (
    RestartContext,
    launch_detached_shell_script,
    render_template,
    temp_script_path,
    write_script,
)


SH_TEMPLATE = r"""#!/usr/bin/env bash
sleep 2
if launchctl print "gui/$UID/com.arena.bridge" >/dev/null 2>&1; then
    launchctl kickstart -k "gui/$UID/com.arena.bridge"
fi
for i in $(seq 1 12); do
    if curl -fsS http://127.0.0.1:__PORT__/health >/dev/null 2>&1; then
        rm -f "$0"; exit 0
    fi
    sleep 1
done
TOK=""
[[ -f "__TOKEN_FILE__" ]] && TOK="$(cat '__TOKEN_FILE__' | tr -d '
 ')"
nohup python3 -u "__BRIDGE__" serve --root "$HOME" --profile owner-shell ${TOK:+--token "$TOK"} --port __PORT__ >/dev/null 2>&1 &
disown
rm -f "$0"
"""


def spawn_darwin_respawn_helper(ctx: RestartContext) -> tuple[bool, str]:
    path = temp_script_path("arena_respawn", ".sh", ctx.pid)
    script = render_template(SH_TEMPLATE, ctx)
    try:
        write_script(path, script, executable=True)
        launch_detached_shell_script(path)
        return True, f"detached .sh (file={path.name})"
    except Exception as e:
        return False, f"spawn failed: {e}"

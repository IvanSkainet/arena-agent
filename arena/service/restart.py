"""Bridge restart/respawn helper facade."""
from __future__ import annotations

from arena.service.restart_common import build_restart_context
from arena.service.restart_darwin import spawn_darwin_respawn_helper
from arena.service.restart_linux import spawn_linux_respawn_helper
from arena.service.restart_windows import spawn_windows_respawn_helper


def spawn_respawn_helper(port: int, *, service_info_sync) -> tuple[bool, str]:
    """Spawn a detached helper that survives bridge exit and relaunches the bridge."""
    ctx = build_restart_context(port)
    if ctx.sys_name == "Windows":
        return spawn_windows_respawn_helper(ctx, service_info_sync=service_info_sync)
    if ctx.sys_name == "Linux":
        return spawn_linux_respawn_helper(ctx)
    if ctx.sys_name == "Darwin":
        return spawn_darwin_respawn_helper(ctx)
    return False, f"unsupported platform: {ctx.sys_name}"


__all__ = ["spawn_respawn_helper"]

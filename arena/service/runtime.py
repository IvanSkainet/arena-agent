"""Service manager, process-status, and restart helper facade."""
from __future__ import annotations

from arena.service.info import _service_info_sync
from arena.service.restart import spawn_respawn_helper as _restart_spawn_respawn_helper
from arena.service.status import _sys_svc_sync
from arena.service.windows import (
    _ps_utf8_command,
    _sc_query_running,
    _windows_bridge_processes,
    _windows_scheduled_task_info,
)


def _spawn_respawn_helper(port: int) -> tuple[bool, str]:
    return _restart_spawn_respawn_helper(port, service_info_sync=_service_info_sync)


__all__ = [
    "_ps_utf8_command",
    "_sc_query_running",
    "_service_info_sync",
    "_spawn_respawn_helper",
    "_sys_svc_sync",
    "_windows_bridge_processes",
    "_windows_scheduled_task_info",
]

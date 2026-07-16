"""hardware/inventory and exec handler wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable

from arena.wiring.env import RuntimeEnv


def build_hardware_exec_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build hardware/inventory and exec handler registries from compatibility globals."""
    env = RuntimeEnv(g)
    registry: dict[str, Callable] = {}

    _hardware_handler_ctx = env.HandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        slow_executor=env._SLOW_EXECUTOR,
        inventory_sync=g["_inventory_sync"],
        hardware_sync=g["_hardware_from_inventory_sync"],
    )
    _hardware_handlers = env.make_hardware_handlers(_hardware_handler_ctx)
    env.export_handler_attrs(
        registry,
        _hardware_handlers,
        {"handle_v1_inventory": "inventory", "handle_v1_hardware": "hardware", "handle_v1_hwinfo": "hwinfo", "handle_v1_inventory_registry": "registry"},
    )

    _exec_handler_ctx = env.ExecHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        audit=env.audit,
        blocked_reason=env.blocked_reason,
        control_check=env._control_check,
        is_input_injection_cmd=env._is_input_injection_cmd,
        first_word=env.first_word,
        under_root=env.under_root,
        decode_output=env.decode_output,
        run_shell_command=env.run_shell_command,
        active_processes=env.ACTIVE_PROCESSES,
        active_processes_snapshot=env.active_processes_snapshot,
        cautious_allow=env.CAUTIOUS_ALLOW,
        default_max_output=env.DEFAULT_MAX_OUTPUT,
    )
    _exec_handlers = env.make_exec_handlers(_exec_handler_ctx)
    env.export_handler_attrs(registry, _exec_handlers, {"handle_v1_ps": "ps", "handle_v1_exec": "exec", "handle_v1_kill": "kill", "handle_v1_exec_script": "script", "handle_v1_exec_stream": "stream"})
    return registry


__all__ = ["build_hardware_exec_registries"]

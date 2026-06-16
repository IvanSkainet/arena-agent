# ruff: noqa: F821
"""Legacy hardware/inventory and exec handler wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable


def build_hardware_exec_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build hardware/inventory and exec handler registries from compatibility globals."""
    globals().update(g)
    registry: dict[str, Callable] = {}

    _hardware_handler_ctx = HandlerContext(
        require_auth=require_auth,
        record_request=_record_request,
        cors_json_response=_cors_json_response,
        executor=_EXECUTOR,
        slow_executor=_SLOW_EXECUTOR,
        inventory_sync=g["_inventory_sync"],
        hardware_sync=g["_hardware_from_inventory_sync"],
    )
    _hardware_handlers = make_hardware_handlers(_hardware_handler_ctx)
    export_handler_attrs(
        registry,
        _hardware_handlers,
        {"handle_v1_inventory": "inventory", "handle_v1_hardware": "hardware", "handle_v1_hwinfo": "hwinfo"},
    )

    _exec_handler_ctx = ExecHandlerContext(
        require_auth=require_auth,
        record_request=_record_request,
        cors_json_response=_cors_json_response,
        audit=audit,
        blocked_reason=blocked_reason,
        control_check=_control_check,
        is_input_injection_cmd=_is_input_injection_cmd,
        first_word=first_word,
        under_root=under_root,
        decode_output=decode_output,
        run_shell_command=run_shell_command,
        active_processes=ACTIVE_PROCESSES,
        active_processes_snapshot=active_processes_snapshot,
        cautious_allow=CAUTIOUS_ALLOW,
        default_max_output=DEFAULT_MAX_OUTPUT,
    )
    _exec_handlers = make_exec_handlers(_exec_handler_ctx)
    export_handler_attrs(registry, _exec_handlers, {"handle_v1_ps": "ps", "handle_v1_exec": "exec", "handle_v1_kill": "kill"})
    return registry


__all__ = ["build_hardware_exec_registries"]

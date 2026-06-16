"""Legacy system/admin/public handler wiring extracted from unified_bridge.py."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable


def build_system_public_admin_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build system, admin and public handler registries from compatibility globals."""
    globals().update(g)
    registry: dict[str, Callable] = {}

    _system_handler_registry = build_system_handlers(SystemWiringContext(
        require_auth=require_auth,
        record_request=_record_request,
        cors_json_response=_cors_json_response,
        executor=_EXECUTOR,
        common_status=lambda cfg: common_status(cfg),
        version=VERSION,
        clean_platform_name=get_clean_platform_name,
        doctor_sync=_doctor_sync,
        sysinfo_sync=_sysinfo_sync,
        play_beep_sync=_play_beep_sync,
    ))
    registry.update(_system_handler_registry)

    _admin_handler_registry = build_admin_handlers(AdminWiringContext(
        require_auth=require_auth,
        record_request=_record_request,
        cors_json_response=_cors_json_response,
        executor=_EXECUTOR,
        audit=audit,
        default_token_file=TOKEN_FILE,
        root_agent=ROOT_AGENT,
        subprocess_kwargs=_subprocess_kwargs,
    ))
    registry.update(_admin_handler_registry)

    _public_handler_registry = build_public_handlers(PublicWiringContext(
        record_request=_record_request,
        cors_json_response=_cors_json_response,
        metrics=BRIDGE_METRICS,
        version=VERSION,
        now=time.time,
        hostname=socket.gethostname,
        bridge_port=_get_bridge_port,
    ))
    registry.update(_public_handler_registry)
    return registry


__all__ = ["build_system_public_admin_registries"]

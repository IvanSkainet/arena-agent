"""system/admin/public handler wiring extracted from unified_bridge.py."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable

from arena.wiring.env import RuntimeEnv


def build_system_public_admin_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build system, admin and public handler registries from compatibility globals."""
    env = RuntimeEnv(g)
    registry: dict[str, Callable] = {}

    _system_handler_registry = env.build_system_handlers(env.SystemWiringContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        common_status=lambda cfg: env.common_status(cfg),
        version=env.VERSION,
        clean_platform_name=env.get_clean_platform_name,
        doctor_sync=env._doctor_sync,
        sysinfo_sync=env._sysinfo_sync,
        play_beep_sync=env._play_beep_sync,
    ))
    registry.update(_system_handler_registry)

    _admin_handler_registry = env.build_admin_handlers(env.AdminWiringContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        audit=env.audit,
        default_token_file=env.TOKEN_FILE,
        root_agent=env.ROOT_AGENT,
        subprocess_kwargs=env._subprocess_kwargs,
        sys_funnel_status_sync=env._sys_funnel_sync,
        cloudflared_status_sync=env._cloudflared_status_sync,
        zerotier_status_sync=env._zerotier_status_sync,
        tailscale_funnel_action_sync=env._tailscale_funnel_action_sync,
        cloudflared_funnel_action_sync=env._cloudflared_funnel_action_sync,
        # v4.33.0: ngrok as fourth transport.
        ngrok_status_sync=env._ngrok_status_sync,
    ))
    registry.update(_admin_handler_registry)

    from arena.wiring.platform import MobileWiringContext, build_mobile_handlers
    _mobile_handler_registry = build_mobile_handlers(MobileWiringContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        audit=env.audit,
    ))
    registry.update(_mobile_handler_registry)

    _public_handler_registry = env.build_public_handlers(env.PublicWiringContext(
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        metrics=env.BRIDGE_METRICS,
        version=env.VERSION,
        now=env.time.time,
        hostname=env.socket.gethostname,
        bridge_port=env._get_bridge_port,
    ))
    registry.update(_public_handler_registry)
    return registry


__all__ = ["build_system_public_admin_registries"]

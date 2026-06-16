# ruff: noqa: F821
"""Top-level legacy bridge runtime/wiring orchestration.

Transitional composition layer used while ``unified_bridge.py`` remains a thin
compatibility entrypoint.
"""
from __future__ import annotations

from typing import Any, MutableMapping

from arena.wiring.legacy_auth_runtime import build_legacy_auth_runtime
from arena.wiring.legacy_base import build_legacy_base_runtime
from arena.wiring.legacy_paths import build_legacy_paths
from arena.wiring.legacy_system_helpers import build_legacy_system_helpers


def build_legacy_bridge_runtime(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build legacy runtime state, wrappers, handlers and lifecycle globals."""
    registry: dict[str, Any] = {}

    def update(values: dict[str, Any]) -> None:
        registry.update(values)
        g.update(values)

    update(build_legacy_base_runtime(g))
    update(g["build_runtime_wrappers"](g))
    update(g["build_observability_runtimes"](g))
    update(build_legacy_paths(g))
    update(g["build_mcp_task_runtimes"](g))
    update({"_shutdown_event": None})
    update(g["build_app_lifecycle"](g))
    update(build_legacy_auth_runtime(g))
    update(g["build_early_handler_registries"](g))
    update(build_legacy_system_helpers(g))
    update(g["build_system_public_admin_registries"](g))
    update(g["build_hardware_exec_registries"](g))
    update(g["build_memory_resource_browser_runtimes"](g))
    update({
        "_capabilities_sync": g["make_capabilities_sync"](
            build_capabilities_fn=g["build_capabilities"],
            version=g["VERSION"],
            get_cdp_module=g["_get_cdp_module"],
            cdp_state=g["_cdp_state"],
            detect_desktop_env=g["_detect_desktop_env"],
            service_info_sync=g["_service_info_sync"],
            sys_svc_sync=g["_sys_svc_sync"],
        ),
        "_sys_funnel_sync": g["make_sys_funnel_sync"](
            sys_funnel_status_fn=g["_sys_funnel_status_runtime"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        "_token_path": g["make_token_path"](default_token_file=g["TOKEN_FILE"]),
        "_token_regen_sync": g["make_token_regen_sync"](
            token_regenerate_fn=g["_token_regenerate_runtime"],
            default_token_file=g["TOKEN_FILE"],
        ),
        "_tailscale_funnel_action_sync": g["make_tailscale_funnel_action_sync"](
            tailscale_funnel_action_fn=g["_tailscale_funnel_action_runtime"],
        ),
        "_cloudflared_funnel_action_sync": g["make_cloudflared_funnel_action_sync"](
            cloudflared_funnel_action_fn=g["_cloudflared_funnel_action_runtime"],
            root_agent=g["ROOT_AGENT"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
    })
    update(g["build_service_browser_registries"](g))
    update(g["build_cdp_registries"](g))
    update(g["build_desktop_registries"](g))
    update(g["build_memory_observability_registries"](g))
    update(g["build_tasks_skills_resources_registries"](g))
    return registry


__all__ = ["build_legacy_bridge_runtime"]

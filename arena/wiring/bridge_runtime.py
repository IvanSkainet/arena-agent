"""Top-level bridge runtime/wiring orchestration.

Transitional composition layer used while ``unified_bridge.py`` remains a thin
compatibility entrypoint.
"""
from __future__ import annotations

from typing import Any, MutableMapping

from arena.wiring.app_lifecycle import build_app_lifecycle
from arena.wiring.auth_runtime import build_auth_runtime
from arena.wiring.base_runtime import build_base_runtime
from arena.wiring.cdp_registries import build_cdp_registries
from arena.wiring.desktop_registries import build_desktop_registries
from arena.wiring.domain_runtimes import build_memory_resource_browser_runtimes
from arena.wiring.early_registries import build_early_handler_registries
from arena.wiring.hardware_exec_registries import build_hardware_exec_registries
from arena.wiring.mcp_task_runtime import build_mcp_task_runtimes
from arena.wiring.memory_observability_registries import build_memory_observability_registries
from arena.wiring.observability_runtime import build_observability_runtimes
from arena.wiring.paths_runtime import build_paths_runtime
from arena.wiring.runtime_wrappers import build_runtime_wrappers
from arena.wiring.service_browser_registries import build_service_browser_registries
from arena.wiring.system_helpers import build_system_helpers
from arena.wiring.system_public_admin_registries import build_system_public_admin_registries
from arena.wiring.tasks_skills_resources_registries import build_tasks_skills_resources_registries


def build_bridge_runtime(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build runtime state, wrappers, handlers and lifecycle globals."""
    registry: dict[str, Any] = {}

    def update(values: dict[str, Any]) -> None:
        registry.update(values)
        g.update(values)

    update(build_base_runtime(g))
    update(build_runtime_wrappers(g))
    update(build_observability_runtimes(g))
    update(build_paths_runtime(g))
    update(build_mcp_task_runtimes(g))
    update({"_shutdown_event": None})
    update(build_app_lifecycle(g))
    update(build_auth_runtime(g))
    update(build_early_handler_registries(g))
    update(build_system_helpers(g))
    update(build_hardware_exec_registries(g))
    update(build_memory_resource_browser_runtimes(g))
    update({
        "_zerotier_status_sync": g["make_zerotier_status_sync"](
            zerotier_status_fn=g["_zerotier_status_runtime"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        "_capabilities_sync": g["make_capabilities_sync"](
            build_capabilities_fn=g["build_capabilities"],
            version=g["VERSION"],
            get_cdp_module=g["_get_cdp_module"],
            cdp_state=g["_cdp_state"],
            detect_desktop_env=g["_detect_desktop_env"],
            service_info_sync=g["_service_info_sync"],
            sys_svc_sync=g["_sys_svc_sync"],
            zerotier_status_sync=g["make_zerotier_status_sync"](
                zerotier_status_fn=g["_zerotier_status_runtime"],
                subprocess_kwargs_fn=g["_subprocess_kwargs"],
            ),
            browseract_status_sync=g["make_browseract_status_sync"](
                browseract_status_fn=g["_browseract_status_runtime"],
                subprocess_kwargs_fn=g["_subprocess_kwargs"],
            ),
            mobile_status_sync=g.get("_mobile_status_runtime"),
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
        "_cloudflared_status_sync": g["make_cloudflared_status_sync"](
            cloudflared_funnel_action_fn=g["_cloudflared_funnel_action_runtime"],
            root_agent=g["ROOT_AGENT"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        # v4.33.0: ngrok status sync -- same shape as cloudflared.
        "_ngrok_status_sync": g["make_ngrok_status_sync"](
            root_agent=g["ROOT_AGENT"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        # v4.47.0: bore status sync -- same shape as ngrok.
        "_bore_status_sync": g["make_bore_status_sync"](
            root_agent=g["ROOT_AGENT"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        "_browseract_status_sync": g["make_browseract_status_sync"](
            browseract_status_fn=g["_browseract_status_runtime"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
    })
    update(build_system_public_admin_registries(g))
    update(build_service_browser_registries(g))
    update(build_cdp_registries(g))
    update(build_desktop_registries(g))
    update(build_memory_observability_registries(g))
    update(build_tasks_skills_resources_registries(g))
    return registry


__all__ = ["build_bridge_runtime"]

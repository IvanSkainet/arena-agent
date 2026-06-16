"""Service capability-map compatibility helper."""
from __future__ import annotations

from typing import Any, Callable


def make_capabilities_sync(
    *,
    build_capabilities_fn: Callable[..., dict[str, Any]],
    version: str,
    get_cdp_module: Callable[[], Any],
    cdp_state: dict[str, Any],
    detect_desktop_env: Callable[[], dict[str, Any]],
    service_info_sync: Callable[[], dict[str, Any]],
    sys_svc_sync: Callable[[], dict[str, Any]],
) -> Callable[[], dict[str, Any]]:
    def _capabilities_sync() -> dict[str, Any]:
        """Machine-readable capability map for agents."""
        return build_capabilities_fn(
            version=version,
            cdp_module_available=get_cdp_module() is not None,
            cdp_connected=bool(cdp_state.get("connected")),
            desktop_env=detect_desktop_env(),
            service_info_fn=service_info_sync,
            sys_svc_fn=sys_svc_sync,
        )

    return _capabilities_sync

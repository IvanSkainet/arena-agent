"""Helper for resolving the active/specific CDP tab with HTTP-compatible errors."""
from __future__ import annotations

from typing import Any, Callable


async def cdp_active_tab(
    tab_id: str | None = None,
    *,
    cdp_state: dict[str, Any],
    get_cdp_module: Callable[[], Any],
    cors_json_response: Callable[..., Any],
    log_warning: Callable[..., None],
):
    """Get a CDPTab instance for the given tab_id or the active tab.

    Returns ``(tab, error_response)``. If ``error_response`` is not ``None``,
    callers should return it immediately. The response payload/status values are
    intentionally identical to the historical monolith helper.
    """
    cdp = get_cdp_module()
    if not cdp:
        return None, cors_json_response(
            {"ok": False, "error": "cdp_browser module not found. Install to scripts/ directory."},
            status=500,
        )

    mgr = cdp_state.get("manager")
    if not mgr or not cdp_state["connected"]:
        return None, cors_json_response(
            {"ok": False, "error": "CDP not connected. POST /v1/browser/cdp/connect first."},
            status=400,
        )

    if tab_id:
        tab = mgr.get_tab(tab_id)
        if not tab:
            return None, cors_json_response(
                {"ok": False, "error": f"Tab {tab_id} not found"},
                status=404,
            )
        if not tab.connected:
            return None, cors_json_response(
                {"ok": False, "error": f"Tab {tab_id} is not connected"},
                status=400,
            )
        return tab, None

    tab = mgr.active_tab
    if not tab:
        return None, cors_json_response(
            {"ok": False, "error": "No active tab. Open a tab first."},
            status=400,
        )
    if not tab.connected:
        try:
            await tab.connect()
        except Exception as e:
            log_warning("[CDP] Auto-reconnect failed for tab %s: %s", tab.target_id, e)
        if not tab.connected:
            return None, cors_json_response(
                {"ok": False, "error": "Active tab is not connected and auto-reconnect failed. Try POST /v1/browser/cdp/connect again."},
                status=400,
            )
    return tab, None

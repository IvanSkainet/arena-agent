"""Shared helpers for advanced CDP handlers."""
from __future__ import annotations

from arena.handler_context import CdpAdvancedHandlerContext


async def get_active_browser(ctx: CdpAdvancedHandlerContext):
    """Get the active tab's CDPBrowser instance, or None."""
    mgr = ctx.cdp_state.get("manager")
    if not mgr or not ctx.cdp_state["connected"]:
        return None
    tab = mgr.active_tab
    if not tab or not tab.connected:
        return None
    return tab._browser

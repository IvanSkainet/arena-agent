"""Advanced CDP handlers: session check, stealth helpers, and health dashboard."""
from __future__ import annotations

from dataclasses import dataclass

from arena.browser.cdp.advanced_common import get_active_browser
from arena.browser.cdp.advanced_health import make_cdp_health_handler
from arena.browser.cdp.advanced_session_check import make_cdp_session_check_handler
from arena.browser.cdp.advanced_stealth_extract import make_cdp_stealth_extract_handler
from arena.browser.cdp.advanced_stealth_shot import make_cdp_stealth_shot_handler
from arena.handler_context import CdpAdvancedHandlerContext


@dataclass(frozen=True)
class CdpAdvancedHandlers:
    session_check: object
    stealth_extract: object
    stealth_shot: object
    health: object


def _as_facade_handler(handler):
    try:
        handler.__module__ = __name__
    except Exception:
        pass
    return handler


def make_cdp_advanced_handlers(ctx: CdpAdvancedHandlerContext) -> CdpAdvancedHandlers:
    return CdpAdvancedHandlers(
        session_check=_as_facade_handler(make_cdp_session_check_handler(ctx)),
        stealth_extract=_as_facade_handler(make_cdp_stealth_extract_handler(ctx)),
        stealth_shot=_as_facade_handler(make_cdp_stealth_shot_handler(ctx)),
        health=_as_facade_handler(make_cdp_health_handler(ctx)),
    )

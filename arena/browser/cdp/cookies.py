"""CDP cookie handler factory facade."""
from __future__ import annotations

from dataclasses import dataclass

from arena.browser.cdp.cookie_crud import (
    make_cdp_cookies_clear_handler,
    make_cdp_cookies_delete_handler,
    make_cdp_cookies_get_handler,
    make_cdp_cookies_set_handler,
)
from arena.browser.cdp.cookie_profiles import make_cdp_cookies_profiles_handler
from arena.browser.cdp.cookie_manager import ensure_cookie_manager
from arena.handler_context import CdpCookiesHandlerContext


@dataclass(frozen=True)
class CdpCookiesHandlers:
    get: object
    set: object
    delete: object
    clear: object
    profiles: object


def make_cdp_cookies_handlers(ctx: CdpCookiesHandlerContext) -> CdpCookiesHandlers:
    """Build the CDP cookie route handlers from focused submodules."""
    return CdpCookiesHandlers(
        get=make_cdp_cookies_get_handler(ctx),
        set=make_cdp_cookies_set_handler(ctx),
        delete=make_cdp_cookies_delete_handler(ctx),
        clear=make_cdp_cookies_clear_handler(ctx),
        profiles=make_cdp_cookies_profiles_handler(ctx),
    )


__all__ = ["CdpCookiesHandlers", "ensure_cookie_manager", "make_cdp_cookies_handlers"]

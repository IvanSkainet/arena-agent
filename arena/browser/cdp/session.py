"""CDP session lifecycle handler factory facade."""
from __future__ import annotations

from dataclasses import dataclass

from arena.browser.cdp.session_connect import make_cdp_connect_handler
from arena.browser.cdp.session_disconnect import make_cdp_disconnect_handler
from arena.handler_context import CdpSessionHandlerContext


@dataclass(frozen=True)
class CdpSessionHandlers:
    connect: object
    disconnect: object


def make_cdp_session_handlers(ctx: CdpSessionHandlerContext) -> CdpSessionHandlers:
    """Build CDP connect/disconnect handlers from focused submodules."""
    return CdpSessionHandlers(
        connect=make_cdp_connect_handler(ctx),
        disconnect=make_cdp_disconnect_handler(ctx),
    )


__all__ = ["CdpSessionHandlers", "make_cdp_session_handlers"]

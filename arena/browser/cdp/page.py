"""CDP page action handlers."""
from __future__ import annotations

from dataclasses import dataclass

from arena.browser.cdp.page_capture import make_cdp_capture_handlers
from arena.browser.cdp.page_eval import make_cdp_eval_handler
from arena.browser.cdp.page_input import make_cdp_input_handlers
from arena.browser.cdp.page_nav import make_cdp_navigate_handler
from arena.handler_context import CdpPageHandlerContext


@dataclass(frozen=True)
class CdpPageHandlers:
    navigate: object
    screenshot: object
    dom: object
    eval: object
    click: object
    type: object


def _as_facade_handler(handler):
    try:
        handler.__module__ = __name__
    except Exception:
        pass
    return handler


def make_cdp_page_handlers(ctx: CdpPageHandlerContext) -> CdpPageHandlers:
    screenshot, dom = make_cdp_capture_handlers(ctx)
    click, type_handler = make_cdp_input_handlers(ctx)
    return CdpPageHandlers(
        navigate=_as_facade_handler(make_cdp_navigate_handler(ctx)),
        screenshot=_as_facade_handler(screenshot),
        dom=_as_facade_handler(dom),
        eval=_as_facade_handler(make_cdp_eval_handler(ctx)),
        click=_as_facade_handler(click),
        type=_as_facade_handler(type_handler),
    )

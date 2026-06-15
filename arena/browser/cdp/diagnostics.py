"""CDP diagnostic handlers for launch/raw HTTP/WebSocket probes."""
from __future__ import annotations

from dataclasses import dataclass

from arena.browser.cdp.raw_info import make_cdp_raw_info_handler
from arena.browser.cdp.test_launch import make_cdp_test_launch_handler
from arena.browser.cdp.test_ws import make_cdp_test_ws_handler
from arena.handler_context import CdpDiagnosticHandlerContext


@dataclass(frozen=True)
class CdpDiagnosticHandlers:
    raw_info: object
    test_launch: object
    test_ws: object


def _as_facade_handler(handler):
    """Keep historical __module__ for compatibility tests/import diagnostics."""
    try:
        handler.__module__ = __name__
    except Exception:
        pass
    return handler


def make_cdp_diagnostic_handlers(ctx: CdpDiagnosticHandlerContext) -> CdpDiagnosticHandlers:
    return CdpDiagnosticHandlers(
        raw_info=_as_facade_handler(make_cdp_raw_info_handler(ctx)),
        test_launch=_as_facade_handler(make_cdp_test_launch_handler(ctx)),
        test_ws=_as_facade_handler(make_cdp_test_ws_handler(ctx)),
    )

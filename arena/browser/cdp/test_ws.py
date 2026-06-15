"""CDP diagnostic test ws handler."""
from __future__ import annotations

from urllib.parse import parse_qs

from arena.browser.cdp.test_ws_probe import run_cdp_test_ws_probe
from arena.handler_context import CdpDiagnosticHandlerContext


def make_cdp_test_ws_handler(ctx: CdpDiagnosticHandlerContext):
    async def handle_v1_cdp_test_ws(request):
        """GET /v1/browser/cdp/test-ws — Diagnostic: test WebSocket connectivity to Chromium debug port."""
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()

        cdp = ctx.get_cdp_module()
        if not cdp:
            ctx.record_request(is_error=True)
            return ctx.cors_json_response(
                {"ok": False, "error": "cdp_browser module not found",
                 "ws_connect_ok": False, "tab_ws_connect_ok": False},
                status=500
            )

        qs = parse_qs(request.query_string)
        port = int(qs.get("port", ["9223"])[0])
        result = await run_cdp_test_ws_probe(ctx, cdp, port)
        return ctx.cors_json_response(result)

    return handle_v1_cdp_test_ws

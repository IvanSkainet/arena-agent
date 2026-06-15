"""CDP diagnostic test launch handler facade."""
from __future__ import annotations

import asyncio
from functools import partial
from urllib.parse import parse_qs

from arena.browser.cdp.test_launch_runner import run_test_launch
from arena.handler_context import CdpDiagnosticHandlerContext


def make_cdp_test_launch_handler(ctx: CdpDiagnosticHandlerContext):
    async def handle_v1_cdp_test_launch(request):
        """GET /v1/browser/cdp/test-launch — try launching Chromium and capture output."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        cdp = ctx.get_cdp_module()
        if not cdp:
            ctx.record_request(is_error=True)
            return ctx.cors_json_response(
                {"ok": False, "error": "cdp_browser module not found"},
                status=500,
            )

        qs = parse_qs(request.query_string)
        port = int(qs.get("port", ["9223"])[0])
        headless = qs.get("headless", ["true"])[0].lower() != "false"
        loop = asyncio.get_event_loop()

        try:
            result = await loop.run_in_executor(
                ctx.executor,
                partial(run_test_launch, cdp, port=port, headless=headless),
            )
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True)
            return ctx.cors_json_response(
                {"ok": False, "error": f"Test launch failed: {str(e)}"},
                status=500,
            )

    return handle_v1_cdp_test_launch

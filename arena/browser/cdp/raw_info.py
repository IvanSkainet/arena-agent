"""CDP diagnostic raw info handler."""
from __future__ import annotations

from urllib.parse import parse_qs

from arena.browser.cdp.raw_info_browser import (
    launch_raw_info_browser,
    stop_raw_info_browser,
    wait_for_raw_info_port,
)
from arena.browser.cdp.raw_info_http import fetch_raw_tabs, fetch_raw_version
from arena.browser.cdp.raw_info_ws import probe_raw_info_websocket
from arena.handler_context import CdpDiagnosticHandlerContext
from arena.handler_helpers import authed, err_json


def make_cdp_raw_info_handler(ctx: CdpDiagnosticHandlerContext):
    @authed(ctx)
    async def handle_v1_cdp_raw_info(request):
        """GET /v1/browser/cdp/raw-info — fetch raw CDP HTTP info and probe tab WS."""

        cdp = ctx.get_cdp_module()
        if not cdp:
            ctx.record_request(is_error=True)
            return ctx.cors_json_response(
                {"ok": False, "error": "cdp_browser module not found"},
                status=500,
            )

        qs = parse_qs(request.query_string)
        port = int(qs.get("port", ["9223"])[0])
        result = {
            "ok": False,
            "port": port,
            "raw_version": None,
            "raw_tabs": None,
            "error": None,
        }
        browser_proc = None

        try:
            browser_proc = await launch_raw_info_browser(ctx, cdp, port, result)
            port_ready = await wait_for_raw_info_port(ctx, cdp, port, browser_proc, result)
            if not port_ready:
                return ctx.cors_json_response(result)

            await fetch_raw_version(ctx, port, result)
            page_tabs = await fetch_raw_tabs(ctx, port, result)
            await probe_raw_info_websocket(ctx, page_tabs, port, result)

            if not result.get("ok"):
                # HTTP works but WS doesn't — still useful diagnostic.
                result["ok"] = bool(result.get("raw_version") or result.get("raw_tabs"))
        except Exception as e:
            import traceback

            result["error"] = f"Unhandled: {type(e).__name__}: {e}"
            result["traceback"] = traceback.format_exc()
            ctx.log_error("[raw-info] UNHANDLED: %s\n%s", e, traceback.format_exc())
        finally:
            stop_raw_info_browser(browser_proc)

        return ctx.cors_json_response(result)

    return handle_v1_cdp_raw_info

"""HTTP endpoint helpers for CDP test-ws diagnostics."""
from __future__ import annotations

import asyncio
import json
import re
import urllib.request

from arena.handler_context import CdpDiagnosticHandlerContext


async def fetch_ws_targets(ctx: CdpDiagnosticHandlerContext, port: int, result: dict) -> tuple[str, str]:
    """Fetch /json/version and /json/list and return browser/tab WS URLs."""
    loop = asyncio.get_event_loop()
    raw_version = {}
    browser_ws_url = ""

    try:
        def _get_version():
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as r:
                return json.loads(r.read().decode())

        raw_version = await loop.run_in_executor(None, _get_version)
        browser_ws_url = raw_version.get("webSocketDebuggerUrl", "")
        result["raw_version_keys"] = list(raw_version.keys())
        version_id = raw_version.get("id", "")
        if not version_id and browser_ws_url:
            m = re.search(r"/devtools/browser/([^/]+)", browser_ws_url)
            if m:
                version_id = m.group(1)
        result["version_info"] = {
            "Browser": raw_version.get("Browser", "?")[:50],
            "webSocketDebuggerUrl": (browser_ws_url or "MISSING")[:80],
            "id": version_id or "N/A",
        }
        result["http_endpoint_ok"] = True
        ctx.log_info(
            "[test-ws] /json/version: keys=%s wsUrl=%s id=%s",
            list(raw_version.keys()),
            raw_version.get("webSocketDebuggerUrl", "MISSING")[:60],
            raw_version.get("id", "MISSING")[:30],
        )
    except Exception as e:
        result["raw_version_error"] = f"{type(e).__name__}: {e}"
        result["http_endpoint_ok"] = False
        ctx.log_warning("[test-ws] /json/version FAILED: %s", e)

    raw_tabs = []
    tab_ws_url = ""
    tab_target_id = ""
    try:
        def _get_tabs():
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
                return json.loads(r.read().decode())

        raw_tabs = await loop.run_in_executor(None, _get_tabs)
        page_tabs = [t for t in raw_tabs if t.get("type") == "page"]
        result["tab_count"] = len(raw_tabs)
        result["page_tab_count"] = len(page_tabs)
        if page_tabs:
            tab_ws_url = page_tabs[0].get("webSocketDebuggerUrl", "")
            tab_target_id = page_tabs[0].get("id", "")
            result["tab_target_id"] = tab_target_id
            for i, t in enumerate(page_tabs[:3]):
                ctx.log_info(
                    "[test-ws] page[%d]: id=%s wsUrl=%s url=%s",
                    i,
                    t.get("id", "?")[:20],
                    t.get("webSocketDebuggerUrl", "MISSING")[:60],
                    t.get("url", "?")[:50],
                )
        ctx.log_info("[test-ws] /json/list: %d entries, %d pages", len(raw_tabs), len(page_tabs))
    except Exception as e:
        result["raw_tabs_error"] = f"{type(e).__name__}: {e}"
        ctx.log_warning("[test-ws] /json/list FAILED: %s", e)

    if not browser_ws_url:
        browser_id = raw_version.get("id", "")
        if browser_id:
            browser_ws_url = f"ws://127.0.0.1:{port}/devtools/browser/{browser_id}"
            result["browser_ws_constructed"] = True
            ctx.log_info("[test-ws] Constructed browser WS URL: %s", browser_ws_url)

    if not tab_ws_url and tab_target_id:
        tab_ws_url = f"ws://127.0.0.1:{port}/devtools/page/{tab_target_id}"
        result["tab_ws_constructed"] = True
        ctx.log_info("[test-ws] Constructed tab WS URL: %s", tab_ws_url)

    result["ws_url"] = browser_ws_url or "NONE"
    result["tab_ws_url"] = tab_ws_url[:80] if tab_ws_url else "NONE"
    return browser_ws_url, tab_ws_url

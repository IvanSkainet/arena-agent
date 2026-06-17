"""HTTP probing helpers for CDP raw-info diagnostics."""
from __future__ import annotations

import asyncio
import json
import re
import urllib.request

from arena.handler_context import CdpDiagnosticHandlerContext


def _fetch_json(path: str, port: int):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        raw = response.read().decode()
        return json.loads(raw), raw


async def fetch_raw_version(ctx: CdpDiagnosticHandlerContext, port: int, result: dict) -> None:
    """Fetch and summarize /json/version from Chromium's debug port."""
    loop = asyncio.get_running_loop()
    try:
        version_data, _version_raw = await loop.run_in_executor(None, _fetch_json, "/json/version", port)
        result["raw_version"] = version_data
        result["raw_version_keys"] = list(version_data.keys())
        result["has_webSocketDebuggerUrl"] = "webSocketDebuggerUrl" in version_data
        ws_url = version_data.get("webSocketDebuggerUrl", "")
        result["webSocketDebuggerUrl"] = ws_url or "MISSING"

        version_id = version_data.get("id", "")
        if not version_id and ws_url:
            match = re.search(r"/devtools/browser/([^/]+)", ws_url)
            if match:
                version_id = match.group(1)
        result["version_id"] = version_id or "N/A"
        result["version_browser"] = version_data.get("Browser", "?")
        ctx.log_info("[raw-info] /json/version keys: %s", list(version_data.keys()))
        ctx.log_info("[raw-info] webSocketDebuggerUrl: %s", ws_url or "MISSING")
        ctx.log_info("[raw-info] id: %s", version_id or "N/A")
    except Exception as e:
        result["raw_version_error"] = f"{type(e).__name__}: {e}"
        ctx.log_warning("[raw-info] /json/version fetch failed: %s", e)


async def fetch_raw_tabs(ctx: CdpDiagnosticHandlerContext, port: int, result: dict) -> list[dict]:
    """Fetch and summarize /json/list from Chromium's debug port."""
    loop = asyncio.get_running_loop()
    page_tabs: list[dict] = []
    try:
        tabs_data, _tabs_raw = await loop.run_in_executor(None, _fetch_json, "/json/list", port)
        result["raw_tabs"] = tabs_data
        result["tab_count"] = len(tabs_data)
        page_tabs = [t for t in tabs_data if t.get("type") == "page"]
        result["page_tab_count"] = len(page_tabs)
        result["tab_ws_urls"] = [
            {
                "id": t.get("id", "?"),
                "type": t.get("type", "?"),
                "webSocketDebuggerUrl": t.get("webSocketDebuggerUrl", "MISSING"),
                "url": t.get("url", "?")[:80],
            }
            for t in tabs_data[:5]
        ]
        ctx.log_info("[raw-info] /json/list: %d entries, %d pages", len(tabs_data), len(page_tabs))
        for i, tab in enumerate(page_tabs[:3]):
            ctx.log_info(
                "[raw-info]   page[%d]: id=%s wsUrl=%s url=%s",
                i,
                tab.get("id", "?")[:20],
                tab.get("webSocketDebuggerUrl", "MISSING")[:60],
                tab.get("url", "?")[:50],
            )
    except Exception as e:
        result["raw_tabs_error"] = f"{type(e).__name__}: {e}"
        ctx.log_warning("[raw-info] /json/list fetch failed: %s", e)
    return page_tabs

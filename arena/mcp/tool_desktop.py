"""MCP desktop OCR tools via local bridge endpoints."""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from arena.mcp.tool_utils import text_content


def _bridge_call(ctx, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    cfg = ctx.app_config() or {}
    port = int(cfg.get("port", 8765) or 8765)
    token = cfg.get("token", "")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))



def handle_desktop_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    if name == "desktop.ocr":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/ocr", args), ensure_ascii=False))
    if name == "desktop.find_text":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/find_text", args), ensure_ascii=False))
    return None

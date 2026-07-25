"""MCP image.* tools: generic image preprocessing (v4.87.0)."""
from __future__ import annotations

import json
from typing import Any

from arena.image.preprocess import image_health, preprocess_for_ocr
from arena.mcp.tool_utils import text_content


def _handle_image_preprocess(args: dict[str, Any]) -> dict[str, Any]:
    file = str(args.get("file", "") or "").strip()
    if not file:
        return {"ok": False, "error": "missing 'file' argument"}
    return preprocess_for_ocr(
        file,
        output=args.get("output"),
        max_size=int(args.get("max_size") or 2200),
        grayscale=bool(args.get("grayscale", True)),
        autocontrast=bool(args.get("autocontrast", True)),
        threshold=bool(args.get("threshold", False)),
        threshold_value=int(args.get("threshold_value") or 170),
        deskew=bool(args.get("deskew", False)),
    )


def handle_image_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "image.health":
        return text_content(json.dumps(image_health(), ensure_ascii=False))
    if name == "image.preprocess_for_ocr":
        return text_content(json.dumps(_handle_image_preprocess(args), ensure_ascii=False))
    return None


__all__ = ["handle_image_tool"]

"""MCP results that carry a picture as an image content block.

A tool that returns a picture used to put the base64 text into its JSON
answer. A model behind an MCP client cannot look at that; it only pays for
the characters. The picture belongs in an ``image`` block, and the JSON keeps
what a caller needs in words: what was captured, how large the picture is and
how a point in it maps back to the desktop.
"""
from __future__ import annotations

import base64
import binascii
import json
import struct
from typing import Any

# 64 base64 characters decode to 48 bytes, enough for every header read below.
_HEAD_CHARS = 64
# Formats an MCP client can show to a model. A BMP is a real picture, but no client takes it.
_DELIVERABLE = ("image/png", "image/jpeg", "image/webp")


def sniff_image(head: bytes) -> dict[str, Any]:
    """Name the image type from its first bytes, with the pixel size when the header has it."""
    if head[:8] == b"\x89PNG\r\n\x1a\n" and len(head) >= 24:
        width, height = struct.unpack(">II", head[16:24])
        return {"mimeType": "image/png", "width": width, "height": height}
    if head[:2] == b"BM" and len(head) >= 26:
        width, height = struct.unpack("<ii", head[18:26])
        return {"mimeType": "image/bmp", "width": width, "height": abs(height)}
    if head[:3] == b"\xff\xd8\xff":
        return {"mimeType": "image/jpeg"}
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return {"mimeType": "image/webp"}
    return {}


def error_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a refusal in words, marked as an error for the MCP client."""
    return {"isError": True, "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


def _describe(data_b64: str) -> dict[str, Any]:
    try:
        head = base64.b64decode(data_b64[:_HEAD_CHARS], validate=True)
    except (binascii.Error, ValueError):
        return {}
    return sniff_image(head)


def _box(region: Any) -> dict[str, int] | None:
    """Return the region as integers when it has a real size."""
    if not isinstance(region, dict):
        return None
    try:
        box = {key: int(region[key]) for key in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError):
        return None
    return box if min(box["width"], box["height"]) > 0 else None


def _mapping(region: Any, image: dict[str, Any]) -> dict[str, Any] | None:
    """Say how a pixel of the picture maps to the desktop region it shows."""
    box = _box(region)
    # The header gives width and height together or not at all.
    if box is None or not image.get("width"):
        return None
    # An unclipped capture keeps the region's proportions; resizing may cost one pixel of height.
    expected_height = box["height"] * image["width"] / box["width"]
    if abs(image["height"] - expected_height) > 1:
        return {"available": False, "reason": "the picture does not cover the whole requested region"}
    return {"available": True, "origin": {"x": box["x"], "y": box["y"]},
            "scale": round(box["width"] / image["width"], 6),
            "formula": "desktop_x = origin.x + image_x * scale; desktop_y = origin.y + image_y * scale"}


def image_result(meta: dict[str, Any], data_b64: str, region: Any = None) -> dict[str, Any]:
    """Build an MCP result: the description as text first, then the picture itself."""
    image = _describe(data_b64)
    if image.get("mimeType") == "image/bmp":
        return error_result({**meta, "ok": False, "error": "screenshot_is_uncompressed_bmp",
                             "detail": "the capture came back as an uncompressed BMP, which the bridge produces "
                                       "when its Python has no Pillow to encode and resize it; install Pillow on the bridge host"})
    if image.get("mimeType") not in _DELIVERABLE:
        return error_result({**meta, "ok": False, "error": "screenshot_not_an_image",
                             "detail": "the captured bytes are not PNG, JPEG or WebP"})
    described = {**meta, "image": {**image, "delivered_as": "image content block"}}
    described["image_to_desktop"] = _mapping(region, image) or {
        "available": False, "reason": "the desktop region this picture shows is not known"}
    return {"content": [
        {"type": "text", "text": json.dumps(described, ensure_ascii=False)},
        {"type": "image", "data": data_b64, "mimeType": image["mimeType"]},
    ]}


def shot_result(shot: dict[str, Any], region: Any = None) -> dict[str, Any]:
    """Turn a bridge screenshot answer (``ok``, ``data``, ...) into an MCP result."""
    if not shot.get("ok"):
        return error_result(shot)
    # "format" names the REST wire shape (base64 in JSON); here the picture travels as a block.
    meta = {key: value for key, value in shot.items() if key not in ("data", "format")}
    return image_result(meta, str(shot.get("data") or ""), region if region is not None else shot.get("crop_region"))


__all__ = ["error_result", "image_result", "shot_result", "sniff_image"]

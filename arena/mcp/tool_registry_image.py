"""MCP registry for image.* preprocessing tools (v4.87.0)."""
from __future__ import annotations

IMAGE_MCP_TOOLS = [
    {
        "name": "image.health",
        "description": "Diagnose image preprocessing runtime: Pillow required, OpenCV optional for deskew.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "image.preprocess_for_ocr",
        "description": (
            "Preprocess an image file for OCR: grayscale, resize, autocontrast, "
            "optional threshold and optional OpenCV deskew. Returns output PNG path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Input image path on the bridge host."},
                "output": {"type": "string", "description": "Optional output PNG path."},
                "max_size": {"type": "integer", "default": 2200},
                "grayscale": {"type": "boolean", "default": True},
                "autocontrast": {"type": "boolean", "default": True},
                "threshold": {"type": "boolean", "default": False},
                "threshold_value": {"type": "integer", "default": 170},
                "deskew": {"type": "boolean", "default": False},
            },
            "required": ["file"], "additionalProperties": False},
    },
]

__all__ = ["IMAGE_MCP_TOOLS"]

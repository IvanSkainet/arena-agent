"""MCP registry for ocr.* generic image OCR tools (v4.86.0)."""
from __future__ import annotations

OCR_MCP_TOOLS = [
    {
        "name": "ocr.health",
        "description": "Diagnose generic OCR runtime: tesseract binary, tessdata dir and installed languages.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "ocr.bootstrap",
        "description": (
            "Bootstrap generic OCR runtime on Windows: install Tesseract via winget "
            "and download rus.traineddata atomically. Approval-gated because it "
            "installs software and writes runtime data."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "force": {"type": "boolean", "default": False},
                "install_tesseract": {"type": "boolean", "default": True},
                "ensure_eng": {"type": "boolean", "default": False},
                "rus_url": {"type": "string"},
                "eng_url": {"type": "string"},
            },
            "additionalProperties": False},
    },
    {
        "name": "ocr.extract",
        "description": (
            "Run OCR on any image file on the bridge host with Tesseract and return "
            "plain text plus word bounding boxes. Use this for pulled phone photos, "
            "documents, screenshots, receipts and notes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Absolute path to image file on the bridge host."},
                "lang": {"type": "string", "default": "eng+rus"},
                "psm": {"type": "integer", "default": 6},
                "min_confidence": {"type": "integer", "default": 40},
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 20},
                "timeout": {"type": "number", "default": 120},
                "preprocess": {"type": "boolean", "default": False},
                "preprocess_max_size": {"type": "integer", "default": 2200},
                "preprocess_grayscale": {"type": "boolean", "default": True},
                "preprocess_autocontrast": {"type": "boolean", "default": True},
                "preprocess_threshold": {"type": "boolean", "default": False},
                "preprocess_threshold_value": {"type": "integer", "default": 170},
                "preprocess_deskew": {"type": "boolean", "default": False},
            },
            "required": ["file"], "additionalProperties": False},
    },
    {
        "name": "ocr.extract_best",
        "description": (
            "Run multiple OCR/preprocess variants on an image file, score them "
            "by word count/confidence/noise, and return the best result plus "
            "diagnostics for every variant."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Absolute path to image file on the bridge host."},
                "lang": {"type": "string", "default": "eng+rus"},
                "min_confidence": {"type": "integer", "default": 25},
                "timeout": {"type": "number", "default": 120},
                "max_variants": {"type": "integer", "default": 6},
            },
            "required": ["file"], "additionalProperties": False},
    },
]

__all__ = ["OCR_MCP_TOOLS"]

"""MCP registry for document.* structuring tools (v4.89.0)."""
from __future__ import annotations

DOCUMENT_MCP_TOOLS = [
    {
        "name": "document.input_quality",
        "description": "Assess whether raw OCR/ASR/text is usable for document extraction; detects noise-heavy OCR before false tasks are created.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "source_quality": {"type": "object"},
            },
            "required": ["text"], "additionalProperties": False},
    },
    {
        "name": "document.extract_tasks",
        "description": "Extract checklist-style tasks from raw text/OCR/ASR output into stable JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "language": {"type": "string", "default": "auto"},
                "source_quality": {"type": "object"},
                "quality_gate": {"type": "boolean", "default": True},
                "allow_low_quality": {"type": "boolean", "default": False},
            },
            "required": ["text"], "additionalProperties": False},
    },
    {
        "name": "document.structure",
        "description": (
            "Structure raw text/OCR/ASR/vision-derived content. Supports kind=auto, "
            "task_note and physics_homework. Returns deterministic JSON, no external LLM calls."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "kind": {"type": "string", "default": "auto"},
                "language": {"type": "string", "default": "auto"},
            },
            "required": ["text"], "additionalProperties": False},
    },
]

__all__ = ["DOCUMENT_MCP_TOOLS"]

"""MCP registry for asr.* speech-to-text tools (v4.58.0)."""
from __future__ import annotations


ASR_MCP_TOOLS = [
    {
        "name": "asr.transcribe",
        "description": (
            "Transcribe an audio file locally with whisper.cpp. "
            "Auto-converts m4a/mp4/webm/opus/etc via ffmpeg if it's on "
            "PATH. Model discovery: `model` arg → ARENA_WHISPER_MODEL "
            "env → first ggml-*.bin under ~/.whisper. Returns "
            "{text, language, segments, model, duration_ms}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Absolute path to audio file on the bridge host."},
                "model": {"type": "string", "description": "Optional path to ggml-*.bin. Overrides env/auto-discovery."},
                "language": {"type": "string", "description": "ISO language code (e.g. 'ru', 'en') or 'auto'."},
                "translate": {"type": "boolean", "default": False, "description": "Translate to English."},
                "threads": {"type": "integer", "description": "CPU threads (defaults to whisper.cpp's own default)."},
                "timeout": {"type": "number", "default": 120, "description": "Seconds, clamped [10, 900]."},
            },
            "required": ["file"],
        },
    },
    {
        "name": "asr.models",
        "description": (
            "List discovered whisper models under ~/.whisper, "
            "/usr/share/whisper.cpp, and ARENA_WHISPER_MODEL. "
            "Also reports which whisper binary is on PATH."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

__all__ = ["ASR_MCP_TOOLS"]

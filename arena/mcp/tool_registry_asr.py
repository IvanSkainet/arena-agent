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
            "required": ["file"], "additionalProperties": False},
    },
    {
        "name": "asr.models",
        "description": (
            "List discovered whisper models under ~/.whisper, "
            "/usr/share/whisper.cpp, and ARENA_WHISPER_MODEL. "
            "Reports size/partial validity and the selected model."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "asr.health",
        "description": (
            "Diagnose the local ASR runtime: ffmpeg, whisper-cli, discovered "
            "models, selected model, PATH and bootstrap hint. Safe/read-only."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "asr.bootstrap",
        "description": (
            "Bootstrap the Windows ASR runtime by downloading ffmpeg, official "
            "whisper.cpp Windows binaries and a ggml model into user-local "
            "paths (~/.local/bin and ~/.whisper). Uses atomic .tmp -> final "
            "model downloads so interrupted downloads are never considered valid."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "default": "small", "description": "tiny/base/small/medium or ggml-*.bin"},
                "force": {"type": "boolean", "default": False, "description": "redownload model even if present"},
                "bin_dir": {"type": "string", "description": "override binary destination (must be on PATH)"},
                "model_dir": {"type": "string", "description": "override model destination"},
                "whisper_zip_url": {"type": "string", "description": "override whisper.cpp Windows zip URL"},
                "model_url": {"type": "string", "description": "override model URL"},
            },
            "additionalProperties": False},
    },
]

__all__ = ["ASR_MCP_TOOLS"]

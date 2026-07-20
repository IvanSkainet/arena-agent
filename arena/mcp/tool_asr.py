"""MCP asr.* tools: local speech-to-text via whisper.cpp.

Introduced in v4.58.0.

Design rationale — before this release, "transcribe audio" was
``exec "whisper-cli -m ... -f ... -otxt"`` which:
  1. was classified ``dangerous`` (any exec is),
  2. gave the caller raw stdout to parse,
  3. hard-coded model paths inside scenario steps.

``asr.transcribe`` centralises the invocation:
  - Model discovery: explicit ``model`` arg → ``ARENA_WHISPER_MODEL``
    env var → first ``ggml-*.bin`` under ``~/.whisper/`` → error with
    a hint on how to download one.
  - Format handling: whisper-cli speaks flac/mp3/ogg/wav. We accept any
    of those directly and use ffmpeg to convert m4a/aac/mp4/webm/opus
    when it's on PATH (no exec-costume — subprocess call from the
    handler itself).
  - Output shape: ``{ok, text, language, duration, segments: [...], model}``
    parsed from whisper-cli's JSON output (``-oj`` flag). Falls back
    to plain text if -oj not honoured.
  - Timeout bounded [10s, 900s].
  - Cross-platform: on Windows, requires ``whisper-cli.exe`` on PATH.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from arena.mcp.tool_utils import text_content


_DEFAULT_TIMEOUT = 120.0
_MIN_TIMEOUT = 10.0
_MAX_TIMEOUT = 900.0

_WHISPER_NATIVE_FORMATS = {".wav", ".flac", ".mp3", ".ogg"}
_CONVERTIBLE_FORMATS = {".m4a", ".aac", ".mp4", ".webm", ".opus", ".mkv", ".mov", ".3gp", ".amr"}


def _err(msg: str) -> dict[str, Any]:
    return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {msg}"}]}


def _clamp_timeout(raw: Any, default: float = _DEFAULT_TIMEOUT) -> float:
    try:
        t = float(raw)
    except (TypeError, ValueError):
        return default
    return max(_MIN_TIMEOUT, min(_MAX_TIMEOUT, t))


def _find_whisper_binary() -> str | None:
    for name in ("whisper-cli", "whisper.cpp", "whisper-cpp", "main"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _find_model(explicit: str | None) -> tuple[str | None, str | None]:
    """Return (path, error_hint). If explicit is given and exists, use it.
    Else check ARENA_WHISPER_MODEL, else scan ~/.whisper/.
    """
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return str(p), None
        return None, f"model file not found: {explicit}"

    env = os.environ.get("ARENA_WHISPER_MODEL", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return str(p), None
        return None, f"ARENA_WHISPER_MODEL points to non-existent file: {env}"

    for candidate in [Path.home() / ".whisper", Path("/usr/share/whisper.cpp"),
                      Path("/usr/share/whisper-cpp"), Path("/opt/whisper.cpp/models")]:
        if candidate.is_dir():
            for f in sorted(candidate.glob("ggml-*.bin")):
                return str(f), None
    return None, ("no whisper model found. Download one e.g. "
                  "`mkdir -p ~/.whisper && curl -L "
                  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin "
                  "-o ~/.whisper/ggml-base.bin`, or set ARENA_WHISPER_MODEL, "
                  "or pass model=<path> to asr.transcribe.")


def _convert_to_wav(src: Path, work_dir: Path, timeout: float) -> tuple[Path | None, str | None]:
    """Convert src to 16 kHz mono wav using ffmpeg. Returns (path, error)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None, f"cannot decode {src.suffix} without ffmpeg on PATH"
    out = work_dir / (src.stem + ".converted.wav")
    try:
        r = subprocess.run(  # nosec B603 -- fully controlled args, no shell # nosemgrep: dangerous-subprocess-use-audit
            [ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
             "-ar", "16000", "-ac", "1", str(out)],
            capture_output=True, timeout=min(timeout, 120), text=True,
        )
    except subprocess.TimeoutExpired:
        return None, "ffmpeg timed out"
    if r.returncode != 0:
        return None, f"ffmpeg failed: {r.stderr[-400:]}"
    if not out.exists():
        return None, "ffmpeg produced no output"
    return out, None


def _parse_whisper_json(path: Path) -> dict[str, Any] | None:
    """whisper-cli -oj writes <input>.json alongside output."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _handle_asr_transcribe(args: dict[str, Any]) -> dict[str, Any]:
    src_arg = str(args.get("file", "") or "").strip()
    if not src_arg:
        return _err("missing 'file' argument")
    src = Path(src_arg).expanduser()
    if not src.exists():
        return _err(f"file not found: {src}")
    if not src.is_file():
        return _err(f"not a file: {src}")

    binary = _find_whisper_binary()
    if not binary:
        return _err("whisper-cli not on PATH. Install `whisper-cpp` (Arch: pacman -S whisper-cpp).")

    model, model_err = _find_model(args.get("model"))
    if not model:
        return _err(model_err or "no model")

    language = str(args.get("language", "") or "").strip() or "auto"
    translate = bool(args.get("translate", False))
    threads = args.get("threads")
    timeout = _clamp_timeout(args.get("timeout"))

    work_dir = Path(tempfile.mkdtemp(prefix="arena-asr-"))
    try:
        # Convert to wav if needed.
        suffix = src.suffix.lower()
        input_path = src
        if suffix not in _WHISPER_NATIVE_FORMATS:
            if suffix not in _CONVERTIBLE_FORMATS:
                # Try to convert anyway; ffmpeg often knows more formats
                # than we hardcode. But be honest about it in the response.
                pass
            converted, cerr = _convert_to_wav(src, work_dir, timeout)
            if not converted:
                return _err(cerr or "conversion failed")
            input_path = converted

        out_prefix = work_dir / "out"
        cmd: list[str] = [
            binary,
            "-m", model,
            "-f", str(input_path),
            "-oj",  # JSON output
            "-of", str(out_prefix),
            "-l", language,
        ]
        if translate:
            cmd.append("-tr")
        if threads:
            try:
                cmd.extend(["-t", str(int(threads))])
            except (TypeError, ValueError):
                pass

        try:
            proc = subprocess.run(  # nosec B603 -- fully controlled args, no shell # nosemgrep: dangerous-subprocess-use-audit
                cmd, capture_output=True, timeout=timeout, text=True,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"whisper-cli timed out after {timeout}s"}

        if proc.returncode != 0:
            return {
                "ok": False,
                "error": f"whisper-cli exit {proc.returncode}",
                "stderr": proc.stderr[-2000:],
            }

        # Parse JSON output.
        json_data = _parse_whisper_json(out_prefix.with_suffix(".json"))
        if json_data:
            # whisper.cpp JSON shape: {result:..., transcription:[{text,offsets,...}]}
            transcript_lines = []
            segments = []
            trs = json_data.get("transcription") or []
            for seg in trs:
                text = str(seg.get("text", "")).strip()
                if text:
                    transcript_lines.append(text)
                segments.append({
                    "start_ms": (seg.get("offsets") or {}).get("from"),
                    "end_ms":   (seg.get("offsets") or {}).get("to"),
                    "text": text,
                })
            full_text = " ".join(transcript_lines).strip()
            result = json_data.get("result") or {}
            return {
                "ok": True,
                "text": full_text,
                "language": str(result.get("language", language)),
                "segments": segments,
                "segment_count": len(segments),
                "model": model,
                "binary": binary,
                "duration_ms": segments[-1]["end_ms"] if segments and segments[-1].get("end_ms") else None,
            }

        # Fall back to stdout parsing.
        return {
            "ok": True,
            "text": proc.stdout.strip(),
            "language": language,
            "model": model,
            "binary": binary,
            "segments": [],
            "note": "whisper-cli did not emit -oj JSON; returning raw stdout only",
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _handle_asr_models(_args: dict[str, Any]) -> dict[str, Any]:
    """List discovered whisper models."""
    found = []
    for candidate in [Path.home() / ".whisper", Path("/usr/share/whisper.cpp"),
                      Path("/usr/share/whisper-cpp"), Path("/opt/whisper.cpp/models")]:
        if candidate.is_dir():
            for f in sorted(candidate.glob("ggml-*.bin")):
                try:
                    size = f.stat().st_size
                except OSError:
                    size = None
                found.append({"path": str(f), "name": f.name, "size_bytes": size})
    env = os.environ.get("ARENA_WHISPER_MODEL", "")
    return {
        "ok": True,
        "models": found,
        "count": len(found),
        "env_model": env or None,
        "binary": _find_whisper_binary(),
    }


def handle_asr_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "asr.transcribe":
        return text_content(json.dumps(_handle_asr_transcribe(args), ensure_ascii=False))
    if name == "asr.models":
        return text_content(json.dumps(_handle_asr_models(args), ensure_ascii=False))
    return None


__all__ = ["handle_asr_tool"]

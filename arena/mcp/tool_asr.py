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
import platform
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from arena.mcp.tool_utils import text_content

_DEFAULT_TIMEOUT = 120.0
_MIN_TIMEOUT = 10.0
_MAX_TIMEOUT = 900.0

_WHISPER_NATIVE_FORMATS = {".wav", ".flac", ".mp3", ".ogg"}
_CONVERTIBLE_FORMATS = {".m4a", ".aac", ".mp4", ".webm", ".opus", ".mkv", ".mov", ".3gp", ".amr"}

_DEFAULT_ASR_BIN_DIR = Path.home() / ".local" / "bin"
_DEFAULT_MODEL_DIR = Path.home() / ".whisper"
_DEFAULT_WHISPER_VERSION = "v1.9.1"
_DEFAULT_BOOTSTRAP_MODEL = "small"
_FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
_WHISPER_ZIP_URL = (
    "https://github.com/ggml-org/whisper.cpp/releases/download/"
    f"{_DEFAULT_WHISPER_VERSION}/whisper-bin-x64.zip"
)
_MODEL_URL_TMPL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{name}?download=true"

# Hosts the bootstrap is allowed to fetch from. Derived from the three
# default URLs above rather than typed out again, so adding a source
# means changing the URL constant and nothing else can drift (bug #55).
_ALLOWED_DOWNLOAD_HOSTS = frozenset(
    urllib.parse.urlparse(u).hostname or ""
    for u in (_FFMPEG_ZIP_URL, _WHISPER_ZIP_URL, _MODEL_URL_TMPL)
)
_KNOWN_MODEL_MIN_BYTES = {
    "ggml-tiny.bin": 70_000_000,
    "ggml-base.bin": 140_000_000,
    "ggml-small.bin": 300_000_000,
    "ggml-medium.bin": 1_000_000_000,
}
_MODEL_PREFERENCE = ("ggml-small.bin", "ggml-base.bin", "ggml-medium.bin", "ggml-tiny.bin")


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


def _model_health(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    min_size = _KNOWN_MODEL_MIN_BYTES.get(path.name)
    partial = path.suffix == ".tmp" or (min_size is not None and (size or 0) < min_size)
    return {
        "path": str(path),
        "name": path.name,
        "size_bytes": size,
        "min_expected_bytes": min_size,
        "valid": bool(size and not partial),
        "partial": partial,
    }


def _model_dirs() -> list[Path]:
    return [Path.home() / ".whisper", Path("/usr/share/whisper.cpp"),
            Path("/usr/share/whisper-cpp"), Path("/opt/whisper.cpp/models")]


def _discover_models() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for candidate in _model_dirs():
        if candidate.is_dir():
            for f in sorted(candidate.glob("ggml-*.bin")):
                found.append(_model_health(f))
    return found


def _find_model(explicit: str | None) -> tuple[str | None, str | None]:
    """Return (path, error_hint). Prefer explicit/env, then small→base.

    Known ggml model names are size-checked so interrupted downloads are not
    mistaken for usable models (a failure the voice scenario exposed).
    """
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            return None, f"model file not found: {explicit}"
        h = _model_health(p)
        if h["valid"]:
            return str(p), None
        return None, f"model appears partial/corrupt: {p} ({h.get('size_bytes')} bytes)"

    env = os.environ.get("ARENA_WHISPER_MODEL", "").strip()
    if env:
        p = Path(env).expanduser()
        if not p.exists():
            return None, f"ARENA_WHISPER_MODEL points to non-existent file: {env}"
        h = _model_health(p)
        if h["valid"]:
            return str(p), None
        return None, f"ARENA_WHISPER_MODEL appears partial/corrupt: {env} ({h.get('size_bytes')} bytes)"

    models = _discover_models()
    valid = [m for m in models if m.get("valid")]
    by_name = {m["name"]: m for m in valid}
    for name in _MODEL_PREFERENCE:
        if name in by_name:
            return str(by_name[name]["path"]), None
    if valid:
        return str(sorted(valid, key=lambda m: m["name"])[0]["path"]), None
    partials = [m for m in models if m.get("partial")]
    if partials:
        return None, f"only partial/corrupt whisper models found: {[m['name'] for m in partials]}"
    return None, ("no whisper model found. Run asr.bootstrap, or download e.g. "
                  "`ggml-small.bin` into ~/.whisper, or set ARENA_WHISPER_MODEL, "
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
    """List discovered whisper models with partial/corrupt detection."""
    found = _discover_models()
    env = os.environ.get("ARENA_WHISPER_MODEL", "")
    selected, selected_err = _find_model(None)
    return {
        "ok": True,
        "models": found,
        "count": len(found),
        "env_model": env or None,
        "selected_model": selected,
        "selected_error": selected_err,
        "binary": _find_whisper_binary(),
    }


def _require_https(url: str) -> None:
    """Refuse any URL that is not plain HTTPS.

    v4.164.0 (bug #55): `asr.bootstrap` accepts `model_url` and
    `whisper_zip_url` straight from the tool call, and `_download_atomic`
    handed them to `urllib.request.urlopen`, which speaks whatever scheme
    it is given. Verified by execution:

        _download_atomic("file:///etc/hostname", dest)
        -> ok: True, and dest contained the host's name

    So a "download" could read local files, and `http://` was accepted
    too -- an unencrypted fetch of a binary that is then run as
    whisper-cli.

    The host is pinned as well as the scheme. Allowing arbitrary HTTPS
    would still let a caller point the bootstrap at any server and have
    the result executed; the three hosts below are the ones the default
    URLs already use, derived from those constants so the two cannot
    drift apart.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(
            f"refusing to download over {parsed.scheme or 'no'} scheme: "
            f"only https is allowed (got {url[:80]!r})")
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_DOWNLOAD_HOSTS:
        raise ValueError(
            f"refusing to download from {host!r}: ASR assets are fetched "
            f"from {sorted(_ALLOWED_DOWNLOAD_HOSTS)} only. Download the "
            f"file yourself and pass a local path if you need another "
            f"source.")


def _download_atomic(url: str, dest: Path, *, force: bool = False) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        return {"ok": True, "path": str(dest), "size_bytes": dest.stat().st_size, "skipped": True}
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    _require_https(url)
    req = urllib.request.Request(url, headers={"User-Agent": "arena-agent"})
    with urllib.request.urlopen(  # nosec B310 -- controlled HTTPS bootstrap URL/override is an approved runtime installer input # nosemgrep: dynamic-urllib-use-detected -- ASR bootstrap downloads approved HTTPS runtime assets; caller must approve asr.bootstrap
        req, timeout=60) as r, tmp.open("wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    size = tmp.stat().st_size
    tmp.replace(dest)
    return {"ok": True, "path": str(dest), "size_bytes": size, "skipped": False}


def _extract_from_zip(zip_path: Path, wanted: str, dest_dir: Path) -> dict[str, Any]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        matches = [n for n in z.namelist() if n.replace("\\", "/").endswith(wanted)]
        if not matches:
            return {"ok": False, "error": f"{wanted} not found in {zip_path}"}
        member = matches[0]
        out = dest_dir / Path(wanted).name
        with z.open(member) as src, out.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        return {"ok": True, "path": str(out), "member": member, "size_bytes": out.stat().st_size}


def _copy_whisper_dir(zip_path: Path, dest_dir: Path) -> dict[str, Any]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        cli = [n for n in z.namelist() if n.replace("\\", "/").endswith("whisper-cli.exe")]
        if not cli:
            return {"ok": False, "error": "whisper-cli.exe not found in zip"}
        prefix = str(Path(cli[0]).parent).replace("\\", "/") + "/"
        copied = []
        for n in z.namelist():
            norm = n.replace("\\", "/")
            if not norm.startswith(prefix) or norm.endswith("/"):
                continue
            out = dest_dir / Path(norm).name
            with z.open(n) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            copied.append(out.name)
    return {"ok": True, "dest": str(dest_dir), "copied": sorted(copied)}


def _model_filename(model: str) -> str:
    m = str(model or _DEFAULT_BOOTSTRAP_MODEL).strip().lower()
    if m.startswith("ggml-") and m.endswith(".bin"):
        return m
    return f"ggml-{m}.bin"


def _handle_asr_health(_args: dict[str, Any]) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    binary = _find_whisper_binary()
    model, model_err = _find_model(None)
    return {
        "ok": bool(ffmpeg and binary and model),
        "ffmpeg": ffmpeg,
        "whisper_binary": binary,
        "model": model,
        "model_error": model_err,
        "models": _discover_models(),
        "path": os.environ.get("PATH"),
        "bootstrap_hint": "run asr.bootstrap on Windows if ffmpeg/whisper/model are missing",
    }


def _handle_asr_bootstrap(args: dict[str, Any]) -> dict[str, Any]:
    if platform.system().lower() != "windows":
        return {"ok": False, "error": "asr.bootstrap is currently implemented for Windows hosts only"}
    force = bool(args.get("force", False))
    model_name = _model_filename(str(args.get("model") or _DEFAULT_BOOTSTRAP_MODEL))
    bin_dir = Path(str(args.get("bin_dir") or _DEFAULT_ASR_BIN_DIR)).expanduser()
    model_dir = Path(str(args.get("model_dir") or _DEFAULT_MODEL_DIR)).expanduser()
    work = Path(tempfile.mkdtemp(prefix="arena-asr-bootstrap-"))
    try:
        ff_zip = work / "ffmpeg.zip"
        wh_zip = work / "whisper.zip"
        ff = _download_atomic(_FFMPEG_ZIP_URL, ff_zip, force=True)
        wh = _download_atomic(str(args.get("whisper_zip_url") or _WHISPER_ZIP_URL), wh_zip, force=True)
        ff_exe = _extract_from_zip(ff_zip, "bin/ffmpeg.exe", bin_dir)
        wh_copy = _copy_whisper_dir(wh_zip, bin_dir)
        model_url = str(args.get("model_url") or _MODEL_URL_TMPL.format(name=model_name))
        model = _download_atomic(model_url, model_dir / model_name, force=force)
        health = _handle_asr_health({})
        return {
            "ok": bool(health.get("ok")),
            "bin_dir": str(bin_dir),
            "model_dir": str(model_dir),
            "ffmpeg_zip": ff,
            "whisper_zip": wh,
            "ffmpeg": ff_exe,
            "whisper": wh_copy,
            "model": model,
            "health": health,
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def handle_asr_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "asr.transcribe":
        return text_content(json.dumps(_handle_asr_transcribe(args), ensure_ascii=False))
    if name == "asr.models":
        return text_content(json.dumps(_handle_asr_models(args), ensure_ascii=False))
    if name == "asr.health":
        return text_content(json.dumps(_handle_asr_health(args), ensure_ascii=False))
    if name == "asr.bootstrap":
        return text_content(json.dumps(_handle_asr_bootstrap(args), ensure_ascii=False))
    return None


__all__ = ["handle_asr_tool"]

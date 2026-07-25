"""MCP ocr.* tools: generic image OCR via Tesseract.

Introduced in v4.86.0 after the camera/document scenario showed that OCR
existed only as a desktop-screenshot capability. This module exposes OCR as
a first-class, file-oriented bridge capability:

  * ocr.health    — safe/read-only runtime diagnostics;
  * ocr.bootstrap — Windows runtime bootstrap (Tesseract + rus traineddata);
  * ocr.extract   — OCR any image file and return text + word boxes.

Desktop OCR keeps using its own desktop-screenshot workflow; both share the
same TSV parser/text builder from arena.desktop.ocr.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from arena.desktop.ocr import parse_tesseract_tsv
from arena.desktop.text_matching import build_ocr_text, find_text_matches
from arena.mcp.tool_utils import text_content

_DEFAULT_LANG = "eng+rus"
_TESSERACT_WINGET_ID = "UB-Mannheim.TesseractOCR"
_RUS_TRAINEDDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/rus.traineddata"
_ENG_TRAINEDDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata"


def _err(msg: str) -> dict[str, Any]:
    return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {msg}"}]}


def _candidate_tesseract_paths() -> list[Path]:
    paths: list[Path] = []
    which = shutil.which("tesseract")
    if which:
        paths.append(Path(which))
    home = Path.home()
    for root in [
        home / ".local" / "bin",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tesseract-OCR",
        Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))) / "Programs" / "Tesseract-OCR",
    ]:
        paths.append(root / "tesseract.exe")
    # Preserve order, drop duplicates.
    seen = set()
    out = []
    for p in paths:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _find_tesseract() -> str | None:
    for p in _candidate_tesseract_paths():
        if p.is_file():
            return str(p)
    return None


def _candidate_tessdata_dirs(binary: str | None = None) -> list[Path]:
    dirs: list[Path] = []
    env = os.environ.get("TESSDATA_PREFIX", "").strip()
    if env:
        p = Path(env).expanduser()
        dirs.append(p / "tessdata" if p.name.lower() != "tessdata" else p)
    if binary:
        dirs.append(Path(binary).parent / "tessdata")
    home = Path.home()
    for root in [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tesseract-OCR",
        Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))) / "Programs" / "Tesseract-OCR",
        home / ".local" / "share" / "tessdata",
    ]:
        dirs.append(root if root.name.lower() == "tessdata" else root / "tessdata")
    seen = set()
    out = []
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _find_tessdata_dir(binary: str | None = None) -> str | None:
    for d in _candidate_tessdata_dirs(binary):
        if d.is_dir():
            return str(d)
    return None


def _langs(tessdata_dir: str | None) -> list[str]:
    if not tessdata_dir:
        return []
    try:
        return sorted(p.stem for p in Path(tessdata_dir).glob("*.traineddata"))
    except OSError:
        return []


def _download_atomic(url: str, dest: Path, *, force: bool = False) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        return {"ok": True, "path": str(dest), "size_bytes": dest.stat().st_size, "skipped": True}
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    req = urllib.request.Request(url, headers={"User-Agent": "arena-agent"})
    with urllib.request.urlopen(  # nosec B310 -- controlled HTTPS bootstrap URL/override is an approved runtime installer input # nosemgrep: dynamic-urllib-use-detected -- OCR bootstrap downloads approved HTTPS runtime assets; caller must approve ocr.bootstrap
        req, timeout=60) as r, tmp.open("wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    size = tmp.stat().st_size
    tmp.replace(dest)
    return {"ok": True, "path": str(dest), "size_bytes": size, "skipped": False}


def _handle_ocr_health(_args: dict[str, Any]) -> dict[str, Any]:
    binary = _find_tesseract()
    tessdata = _find_tessdata_dir(binary)
    langs = _langs(tessdata)
    return {
        "ok": bool(binary and tessdata and ("eng" in langs or "rus" in langs)),
        "tesseract": binary,
        "tessdata": tessdata,
        "languages": langs,
        "has_eng": "eng" in langs,
        "has_rus": "rus" in langs,
        "path": os.environ.get("PATH"),
        "bootstrap_hint": "run ocr.bootstrap on Windows if tesseract or rus.traineddata is missing",
    }


def _run(cmd: list[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 -- controlled argv, no shell
        cmd, capture_output=True, text=True, timeout=timeout,
    )


def _handle_ocr_bootstrap(args: dict[str, Any]) -> dict[str, Any]:
    if platform.system().lower() != "windows":
        return {"ok": False, "error": "ocr.bootstrap is currently implemented for Windows hosts only"}
    force = bool(args.get("force", False))
    install = bool(args.get("install_tesseract", True))
    if install:
        winget = shutil.which("winget")
        if not winget:
            return {"ok": False, "error": "winget not found; install Tesseract manually or put tesseract on PATH"}
        # winget returns non-zero when the package is already installed on
        # some versions; continue and validate via health below.
        _run([winget, "install", "--id", _TESSERACT_WINGET_ID, "-e",
              "--accept-source-agreements", "--accept-package-agreements",
              "--silent"], timeout=300)
    binary = _find_tesseract()
    tessdata = _find_tessdata_dir(binary)
    if not tessdata:
        base = Path(binary).parent if binary else Path.home() / ".local" / "share"
        tessdata = str(base / "tessdata")
    td = Path(tessdata)
    rus = _download_atomic(str(args.get("rus_url") or _RUS_TRAINEDDATA_URL), td / "rus.traineddata", force=force)
    eng = None
    if bool(args.get("ensure_eng", False)):
        eng = _download_atomic(str(args.get("eng_url") or _ENG_TRAINEDDATA_URL), td / "eng.traineddata", force=force)
    return {"ok": True, "tesseract": _find_tesseract(), "tessdata": str(td), "rus": rus, "eng": eng, "health": _handle_ocr_health({})}


def _handle_ocr_extract(args: dict[str, Any]) -> dict[str, Any]:
    file_arg = str(args.get("file", "") or "").strip()
    if not file_arg:
        return _err("missing 'file' argument")
    src = Path(file_arg).expanduser()
    if not src.exists():
        return _err(f"file not found: {src}")
    if not src.is_file():
        return _err(f"not a file: {src}")
    binary = _find_tesseract()
    if not binary:
        return _err("tesseract not found. Run ocr.bootstrap or install Tesseract OCR.")
    tessdata = _find_tessdata_dir(binary)
    lang = str(args.get("lang") or _DEFAULT_LANG)
    psm = int(args.get("psm") or 6)
    min_confidence = max(0, int(args.get("min_confidence") or 40))
    timeout = float(args.get("timeout") or 120)
    query = str(args.get("query") or "").strip()
    max_results = int(args.get("max_results") or 20)
    cmd = [binary, str(src), "stdout", "--psm", str(psm), "-l", lang, "tsv"]
    env = os.environ.copy()
    if tessdata:
        env["TESSDATA_PREFIX"] = str(Path(tessdata))
    try:
        proc = subprocess.run(  # nosec B603 -- controlled argv, no shell
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"tesseract timed out after {timeout}s"}
    if proc.returncode != 0:
        return {"ok": False, "error": f"tesseract exit {proc.returncode}", "stderr": proc.stderr[-2000:]}
    words = parse_tesseract_tsv(proc.stdout, min_confidence=min_confidence)
    matches = find_text_matches(words, query, max_results=max_results) if query else []
    return {
        "ok": True,
        "file": str(src),
        "lang": lang,
        "psm": psm,
        "word_count": len(words),
        "words": words,
        "text": build_ocr_text(words),
        "matches": matches,
        "best_match": matches[0] if matches else None,
        "tesseract": binary,
        "tessdata": tessdata,
    }


def handle_ocr_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "ocr.health":
        return text_content(json.dumps(_handle_ocr_health(args), ensure_ascii=False))
    if name == "ocr.bootstrap":
        return text_content(json.dumps(_handle_ocr_bootstrap(args), ensure_ascii=False))
    if name == "ocr.extract":
        return text_content(json.dumps(_handle_ocr_extract(args), ensure_ascii=False))
    return None


__all__ = ["handle_ocr_tool"]

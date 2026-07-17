"""Desktop OCR parsing and text-target detection helpers."""
from __future__ import annotations

import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any

from arena.desktop.text_matching import build_ocr_text, find_text_matches, line_groups



def parse_tesseract_tsv(tsv: str, *, min_confidence: int = 40, max_words: int = 500) -> list[dict[str, Any]]:
    lines = [line for line in (tsv or "").splitlines() if line.strip()]
    if len(lines) <= 1:
        return []
    words: list[dict[str, Any]] = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        try:
            conf = float(parts[10])
            left, top, width, height = map(int, parts[6:10])
            line_num = int(parts[4])
            block_num = int(parts[2])
            par_num = int(parts[3])
        except (ValueError, TypeError):
            continue
        text = parts[11].strip()
        if not text or conf < min_confidence or width <= 0 or height <= 0:
            continue
        words.append(
            {
                "text": text,
                "confidence": conf,
                "bbox": {"x": left, "y": top, "width": width, "height": height},
                "center": {"x": left + width // 2, "y": top + height // 2},
                "line_num": line_num,
                "block_num": block_num,
                "par_num": par_num,
            }
        )
        if len(words) >= max_words:
            break
    return words


async def ocr_desktop(
    *,
    query: str = "",
    scale: float | None = None,
    max_width: int | None = None,
    quality: int = 80,
    min_confidence: int = 40,
    psm: int = 11,
    max_results: int = 20,
    prefer_active_window: bool = False,
    within_active_window: bool = False,
    active_window: dict[str, Any] | None = None,
    region_x: int | None = None,
    region_y: int | None = None,
    region_width: int | None = None,
    region_height: int | None = None,
    capture_screenshot,
    desktop_exec,
    detect_env,
    audit_fn=None,
) -> dict[str, Any]:
    if shutil.which("tesseract") is None:
        return {"ok": False, "error": "tesseract is not installed"}
    shot = await capture_screenshot(
        fmt="png",
        scale=scale,
        max_width=max_width,
        quality=quality,
        region_x=region_x,
        region_y=region_y,
        region_width=region_width,
        region_height=region_height,
        desktop_exec=desktop_exec,
        detect_env=detect_env,
        audit_fn=audit_fn,
    )
    if not shot.get("ok"):
        return shot
    # v4.42.0: tempfile.mktemp() is TOCTOU-racy -- an attacker
    # with local access can predict the name and pre-create a
    # symlink at that path, redirecting our write to an arbitrary
    # file the bridge user can touch. NamedTemporaryFile(delete=False)
    # opens+creates atomically with O_EXCL, and we clean up in
    # the finally block below.
    tf = tempfile.NamedTemporaryFile(
        suffix=".png", prefix="arena_ocr_", delete=False)
    tf.close()
    tmp = Path(tf.name)
    try:
        tmp.write_bytes(shot["bytes"])
        cmd = f"tesseract {shlex.quote(str(tmp))} stdout --psm {int(psm or 11)} tsv"
        result = await desktop_exec(cmd, timeout=20)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("stderr") or result.get("error") or "OCR failed"}
        words = parse_tesseract_tsv(result.get("stdout", ""), min_confidence=max(0, int(min_confidence or 40)))
        if None not in (region_x, region_y):
            dx = int(region_x or 0)
            dy = int(region_y or 0)
            for word in words:
                word["bbox"]["x"] += dx
                word["bbox"]["y"] += dy
                word["center"]["x"] += dx
                word["center"]["y"] += dy
        matches = []
        if query:
            matches = find_text_matches(
                words,
                query,
                max_results=max_results,
                prefer_active_window=prefer_active_window,
                within_active_window=within_active_window,
                active_window_geometry=(active_window or {}).get("geometry"),
            )
        return {
            "ok": True,
            "query": query,
            "word_count": len(words),
            "words": words,
            "matches": matches,
            "best_match": matches[0] if matches else None,
            "text": build_ocr_text(words),
            "tool": shot.get("tool"),
            "transformed": shot.get("transformed", False),
            "active_window": active_window,
            "prefer_active_window": bool(prefer_active_window),
            "within_active_window": bool(within_active_window),
            "crop_region": shot.get("crop_region"),
        }
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


__all__ = [
    "build_ocr_text",
    "find_text_matches",
    "line_groups",
    "ocr_desktop",
    "parse_tesseract_tsv",
]

"""Desktop OCR and text-target detection helpers."""
from __future__ import annotations

import shlex
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any


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



def _line_groups(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for word in words:
        grouped[(word["block_num"], word["par_num"], word["line_num"])].append(word)
    groups = []
    for key in sorted(grouped):
        groups.append(sorted(grouped[key], key=lambda item: item["bbox"]["x"]))
    return groups



def build_ocr_text(words: list[dict[str, Any]]) -> str:
    return "\n".join(" ".join(word["text"] for word in group) for group in _line_groups(words))



def find_text_matches(words: list[dict[str, Any]], query: str, *, max_results: int = 20) -> list[dict[str, Any]]:
    query = str(query or "").strip()
    if not query:
        return []
    q_tokens = [token.lower() for token in query.split() if token.strip()]
    if not q_tokens:
        return []
    matches: list[dict[str, Any]] = []
    for group in _line_groups(words):
        tokens = [item["text"].lower() for item in group]
        for start in range(len(tokens)):
            if len(q_tokens) == 1:
                ok = q_tokens[0] in tokens[start] or tokens[start] in q_tokens[0]
                end = start + 1
            else:
                end = start + len(q_tokens)
                if end > len(tokens):
                    continue
                window = tokens[start:end]
                ok = all(q in w or w in q for q, w in zip(q_tokens, window))
            if not ok:
                continue
            segment = group[start:end]
            left = min(item["bbox"]["x"] for item in segment)
            top = min(item["bbox"]["y"] for item in segment)
            right = max(item["bbox"]["x"] + item["bbox"]["width"] for item in segment)
            bottom = max(item["bbox"]["y"] + item["bbox"]["height"] for item in segment)
            conf = round(sum(item["confidence"] for item in segment) / len(segment), 2)
            matches.append(
                {
                    "text": " ".join(item["text"] for item in segment),
                    "confidence": conf,
                    "bbox": {"x": left, "y": top, "width": right - left, "height": bottom - top},
                    "center": {"x": left + (right - left) // 2, "y": top + (bottom - top) // 2},
                }
            )
            if len(matches) >= max_results:
                return matches
    return matches


async def ocr_desktop(
    *,
    query: str = "",
    scale: float | None = None,
    max_width: int | None = None,
    quality: int = 80,
    min_confidence: int = 40,
    psm: int = 11,
    max_results: int = 20,
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
        desktop_exec=desktop_exec,
        detect_env=detect_env,
        audit_fn=audit_fn,
    )
    if not shot.get("ok"):
        return shot
    tmp = Path(tempfile.mktemp(suffix=".png", prefix="arena_ocr_"))
    try:
        tmp.write_bytes(shot["bytes"])
        cmd = f"tesseract {shlex.quote(str(tmp))} stdout --psm {int(psm or 11)} tsv"
        result = await desktop_exec(cmd, timeout=20)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("stderr") or result.get("error") or "OCR failed"}
        words = parse_tesseract_tsv(result.get("stdout", ""), min_confidence=max(0, int(min_confidence or 40)))
        matches = find_text_matches(words, query, max_results=max_results) if query else []
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
        }
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

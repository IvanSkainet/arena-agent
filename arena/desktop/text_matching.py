"""OCR text matching and geometry helpers for desktop automation."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any

_WORD_RE = re.compile(r"[0-9A-Za-z]+")
_GEOM_RE = re.compile(r"Position:\s*(-?\d+),(-?\d+).*?Geometry:\s*(\d+)x(\d+)", re.S)


def normalize_text(text: str) -> str:
    return " ".join(_WORD_RE.findall(str(text or "").casefold()))


def coerce_geometry(value: Any) -> dict[str, int] | None:
    if isinstance(value, dict):
        try:
            x = int(value.get("x"))
            y = int(value.get("y"))
            width = int(value.get("width"))
            height = int(value.get("height"))
        except (TypeError, ValueError):
            return None
        if width <= 0 or height <= 0:
            return None
        return {"x": x, "y": y, "width": width, "height": height}
    if isinstance(value, str):
        match = _GEOM_RE.search(value)
        if match:
            x, y, width, height = map(int, match.groups())
            if width > 0 and height > 0:
                return {"x": x, "y": y, "width": width, "height": height}
    return None


def point_in_geometry(center: dict[str, int], geometry: Any) -> bool:
    bounds = coerce_geometry(geometry)
    if not bounds:
        return False
    x = int(center.get("x", 0))
    y = int(center.get("y", 0))
    return (
        bounds["x"] <= x <= bounds["x"] + bounds["width"]
        and bounds["y"] <= y <= bounds["y"] + bounds["height"]
    )


def line_groups(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for word in words:
        grouped[(word["block_num"], word["par_num"], word["line_num"])].append(word)
    return [sorted(grouped[key], key=lambda item: item["bbox"]["x"]) for key in sorted(grouped)]


def build_ocr_text(words: list[dict[str, Any]]) -> str:
    return "\n".join(" ".join(word["text"] for word in group) for group in line_groups(words))


def _segment_score(query_norm: str, query_tokens: list[str], candidate_text: str) -> tuple[str, float] | None:
    candidate_norm = normalize_text(candidate_text)
    if not query_norm or not candidate_norm:
        return None
    candidate_tokens = candidate_norm.split()
    length_ratio = min(len(query_norm), len(candidate_norm)) / max(len(query_norm), len(candidate_norm))
    char_ratio = SequenceMatcher(None, query_norm, candidate_norm).ratio()
    query_counts = Counter(query_tokens)
    candidate_counts = Counter(candidate_tokens)
    overlap = sum(min(query_counts[token], candidate_counts[token]) for token in query_counts)
    token_ratio = overlap / max(len(query_tokens), len(candidate_tokens), 1)

    if candidate_norm == query_norm:
        return "exact", 1.0
    if query_norm in candidate_norm:
        return "phrase", round(0.95 + 0.03 * length_ratio, 4)
    if candidate_norm in query_norm and len(candidate_norm) >= 4 and length_ratio >= 0.75:
        return "truncated", round(0.9 + 0.04 * length_ratio, 4)
    if token_ratio >= 0.8 and char_ratio >= 0.72 and length_ratio >= 0.65:
        return "token", round(0.72 + 0.15 * token_ratio + 0.13 * char_ratio, 4)
    if char_ratio >= 0.86 and length_ratio >= 0.6:
        return "fuzzy", round(0.55 + 0.25 * char_ratio + 0.2 * length_ratio, 4)
    if len(query_tokens) == 1 and len(candidate_tokens) == 1 and char_ratio >= 0.8 and length_ratio >= 0.7:
        return "fuzzy", round(0.52 + 0.28 * char_ratio + 0.2 * length_ratio, 4)
    return None


def find_text_matches(
    words: list[dict[str, Any]],
    query: str,
    *,
    max_results: int = 20,
    prefer_active_window: bool = False,
    within_active_window: bool = False,
    active_window_geometry: Any = None,
) -> list[dict[str, Any]]:
    query_norm = normalize_text(query)
    if not query_norm:
        return []
    query_tokens = query_norm.split()
    if not query_tokens:
        return []

    active_geometry = coerce_geometry(active_window_geometry)
    max_words = max(1, min(max(len(query_tokens) + 2, 2), 8))
    matches: list[dict[str, Any]] = []

    for group in line_groups(words):
        for start in range(len(group)):
            for end in range(start + 1, min(len(group), start + max_words) + 1):
                segment = group[start:end]
                text = " ".join(item["text"] for item in segment)
                scored = _segment_score(query_norm, query_tokens, text)
                if not scored:
                    continue
                left = min(item["bbox"]["x"] for item in segment)
                top = min(item["bbox"]["y"] for item in segment)
                right = max(item["bbox"]["x"] + item["bbox"]["width"] for item in segment)
                bottom = max(item["bbox"]["y"] + item["bbox"]["height"] for item in segment)
                center = {"x": left + (right - left) // 2, "y": top + (bottom - top) // 2}
                inside_active_window = point_in_geometry(center, active_geometry)
                if within_active_window and active_geometry and not inside_active_window:
                    continue
                match_type, score = scored
                confidence = round(sum(item["confidence"] for item in segment) / len(segment), 2)
                if prefer_active_window and inside_active_window:
                    score = round(score + 0.02, 4)
                matches.append(
                    {
                        "text": text,
                        "confidence": confidence,
                        "score": score,
                        "match_type": match_type,
                        "bbox": {"x": left, "y": top, "width": right - left, "height": bottom - top},
                        "center": center,
                        "inside_active_window": inside_active_window,
                    }
                )

    matches.sort(
        key=lambda item: (
            item.get("score", 0.0),
            item.get("inside_active_window", False),
            item.get("confidence", 0.0),
            len(normalize_text(item.get("text", ""))),
        ),
        reverse=True,
    )
    return matches[:max(1, int(max_results or 20))]


__all__ = [
    "build_ocr_text",
    "coerce_geometry",
    "find_text_matches",
    "line_groups",
    "normalize_text",
    "point_in_geometry",
]

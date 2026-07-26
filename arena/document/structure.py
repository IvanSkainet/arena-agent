"""Deterministic document structuring helpers (v4.89.0).

The bridge already has multiple ways to obtain text-ish input (OCR, ASR,
browser/read, file reads, and multimodal agents). This module provides a
small, deterministic layer that turns such input into stable JSON shapes.
It is intentionally heuristic: no external model calls, no hidden magic.
"""
from __future__ import annotations

import re
from typing import Any

_TASK_PREFIX_RE = re.compile(r"^\s*(?:[-*•–—]|\d+[.)]|\[\s?\]|☐|✅|TODO:?|ЗАДАЧИ:?|ДЕЛА:?)\s*", re.I)
_SKIP_HEADINGS = {"todo", "todos", "задачи", "дела", "список", "план"}
_DUE_PATTERNS = [
    (re.compile(r"\bзавтра(?:\s+утром|\s+вечером|\s+дн[её]м)?\b", re.I), "завтра"),
    (re.compile(r"\bсегодня(?:\s+утром|\s+вечером|\s+дн[её]м)?\b", re.I), "сегодня"),
    (re.compile(r"\bвечером\b", re.I), "вечером"),
    (re.compile(r"\bутром\b", re.I), "утром"),
]
_PROBLEM_SPLIT_RE = re.compile(r"(?m)^\s*(\d{1,3})\s*[.)]\s+")
_FORMULA_RE = re.compile(r"[A-Za-zА-Яа-яρρ]\w*\s*=\s*[^\n;,]+")
_VAR_RE = re.compile(
    r"(?P<symbol>[A-Za-zА-Яа-яρρ][A-Za-zА-Яа-я0-9_]*?)\s*=\s*"
    r"(?P<value>[-+]?\d+(?:[,.]\d+)?)\s*(?P<unit>[A-Za-zА-Яа-яΩОм/%²^0-9.*·]*)"
)


def _norm_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "").strip())

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9_-]{1,}")
_NOISE_CHARS = set("|\\/_~=<>[]{}^`$#@*•")


def assess_text_quality(text: str, source_quality: dict[str, Any] | None = None) -> dict[str, Any]:
    """Estimate whether raw OCR/ASR/text is usable for document extraction.

    This is intentionally generic. It does not know about physics/tasks/etc.;
    it detects garbage-heavy text (grid lines, punctuation-only OCR, very low
    OCR confidence) so downstream structuring tools can refuse false positives.
    """
    raw = text or ""
    nonempty = [_norm_line(l) for l in raw.splitlines() if _norm_line(l)]
    chars = [c for c in raw if not c.isspace()]
    alnum = [c for c in chars if c.isalnum()]
    noise = [c for c in chars if c in _NOISE_CHARS]
    words = _WORD_RE.findall(raw)
    line_scores = []
    for line in nonempty:
        line_chars = [c for c in line if not c.isspace()]
        if not line_chars:
            continue
        line_alnum = sum(1 for c in line_chars if c.isalnum()) / len(line_chars)
        line_noise = sum(1 for c in line_chars if c in _NOISE_CHARS) / len(line_chars)
        line_scores.append((line_alnum, line_noise))
    garbage_line_ratio = (
        sum(1 for a, n in line_scores if a < 0.45 or n > 0.35) / len(line_scores)
        if line_scores else 1.0
    )
    short_line_ratio = (
        sum(1 for l in nonempty if len(_WORD_RE.findall(l)) <= 1) / len(nonempty)
        if nonempty else 1.0
    )
    alnum_ratio = len(alnum) / max(1, len(chars))
    noise_ratio = len(noise) / max(1, len(chars))
    source_quality = source_quality or {}
    src_garbage = source_quality.get("garbage_ratio")
    src_short = source_quality.get("short_ratio")
    src_conf = source_quality.get("mean_confidence")
    reasons: list[str] = []
    if len(words) < 2:
        reasons.append("too_few_words")
    if alnum_ratio < 0.45:
        reasons.append("low_alnum_ratio")
    if noise_ratio > 0.30:
        reasons.append("high_noise_ratio")
    if garbage_line_ratio > 0.55:
        reasons.append("garbage_heavy_lines")
    if short_line_ratio > 0.75 and len(nonempty) >= 3:
        reasons.append("mostly_short_lines")
    try:
        if src_garbage is not None and float(src_garbage) > 0.45:
            reasons.append("source_high_garbage_ratio")
        if src_short is not None and float(src_short) > 0.65:
            reasons.append("source_high_short_ratio")
        if src_conf is not None and float(src_conf) < 35:
            reasons.append("source_low_confidence")
    except (TypeError, ValueError):
        pass
    usable = not reasons
    return {
        "ok": True,
        "usable": usable,
        "reasons": reasons,
        "line_count": len(nonempty),
        "char_count": len(raw),
        "word_count": len(words),
        "alnum_ratio": round(alnum_ratio, 3),
        "noise_ratio": round(noise_ratio, 3),
        "garbage_line_ratio": round(garbage_line_ratio, 3),
        "short_line_ratio": round(short_line_ratio, 3),
        "source_quality": source_quality or None,
    }


def _due(text: str) -> str | None:
    for rx, label in _DUE_PATTERNS:
        m = rx.search(text or "")
        if m:
            return m.group(0)
    return None


def extract_tasks(text: str, *, language: str = "auto", source_quality: dict[str, Any] | None = None, quality_gate: bool = True, allow_low_quality: bool = False) -> dict[str, Any]:
    """Extract checklist-like tasks from raw text.

    The algorithm is intentionally conservative: headings are skipped,
    lines that look like formulas/tables are ignored, and each accepted
    line becomes one task with optional due_text.
    """
    quality = assess_text_quality(text, source_quality)
    if quality_gate and not allow_low_quality and not quality.get("usable"):
        return {
            "ok": False,
            "kind": "tasks",
            "language": language,
            "error": "input looks like OCR/noise-heavy text; refusing to extract false tasks",
            "quality": quality,
            "count": 0,
            "tasks": [],
        }
    tasks = []
    for raw in (text or "").splitlines():
        line = _norm_line(raw)
        if not line:
            continue
        stripped = _TASK_PREFIX_RE.sub("", line).strip(" :-–—")
        if not stripped or stripped.lower() in _SKIP_HEADINGS:
            continue
        # Avoid turning pure formulas/noisy OCR rows into tasks.
        if "=" in stripped and len(stripped.split()) <= 5:
            continue
        if len(stripped) < 3:
            continue
        tasks.append({
            "title": stripped,
            "due_text": _due(stripped),
            "source_line": line,
            "done": False,
        })
    return {"ok": True, "kind": "tasks", "language": language, "quality": quality, "count": len(tasks), "tasks": tasks}


def _split_problems(text: str) -> list[tuple[str | None, str]]:
    matches = list(_PROBLEM_SPLIT_RE.finditer(text or ""))
    if not matches:
        return [(None, (text or "").strip())] if (text or "").strip() else []
    out = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((m.group(1), text[start:end].strip()))
    return out


def _extract_variables(block: str) -> list[dict[str, Any]]:
    vars_: list[dict[str, Any]] = []
    for m in _VAR_RE.finditer(block or ""):
        raw_value = m.group("value")
        try:
            value = float(raw_value.replace(",", "."))
        except ValueError:
            value = None
        vars_.append({
            "symbol": m.group("symbol"),
            "raw_value": raw_value,
            "value": value,
            "unit": (m.group("unit") or "").strip(),
        })
    return vars_


def structure_physics_homework(text: str, *, language: str = "ru") -> dict[str, Any]:
    problems = []
    for number, block in _split_problems(text):
        lines = [_norm_line(l) for l in block.splitlines() if _norm_line(l)]
        formulas = [m.group(0).strip() for m in _FORMULA_RE.finditer(block or "")]
        find_lines = [l for l in lines if re.search(r"\b(найти|find|\?)\b", l, re.I)]
        answer_lines = [l for l in lines if re.search(r"\b(ответ|answer)\b", l, re.I)]
        problems.append({
            "number": number,
            "given": _extract_variables(block),
            "find": find_lines,
            "formulas": formulas,
            "answer_lines": answer_lines,
            "raw_text": block,
        })
    return {"ok": True, "kind": "physics_homework", "language": language, "problem_count": len(problems), "problems": problems}


def structure_document(text: str, *, kind: str = "auto", language: str = "auto") -> dict[str, Any]:
    k = (kind or "auto").strip().lower()
    if k in {"tasks", "task_note", "todo"}:
        return extract_tasks(text, language=language)
    if k in {"physics", "physics_homework", "homework"}:
        return structure_physics_homework(text, language=language if language != "auto" else "ru")
    # auto: prefer checklist when multiple task-ish lines exist; otherwise
    # physics if formulas/units dominate; else return a lightweight text doc.
    taskish = extract_tasks(text, language=language, quality_gate=False)
    if taskish.get("count", 0) >= 2:
        return {**taskish, "kind": "task_note"}
    if "=" in (text or "") or re.search(r"\b(Ом|см|мм|м/с|Н|Дж|Вт|R\d?|S\d?|L\d?)\b", text or ""):
        return structure_physics_homework(text, language=language if language != "auto" else "ru")
    return {"ok": True, "kind": "text", "language": language, "text": text or ""}


__all__ = ["assess_text_quality", "extract_tasks", "structure_document", "structure_physics_homework"]

"""Pure view-range validation and new-file content serialization."""
from __future__ import annotations


def _line_number(value) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a line number")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("fractional or nonfinite line number")
    return int(value)


def _parse_view_range(view_range) -> tuple[int, int]:
    if not isinstance(view_range, list) or len(view_range) != 2:
        raise ValueError("view_range must be [start, end] line numbers (1-indexed)")
    try:
        start, end = _line_number(view_range[0]), _line_number(view_range[1])
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("view_range values must be integers") from exc
    return start, end


def _view_bounds(view_range, total_lines: int) -> tuple[int, int]:
    """Validate the optional inclusive one-based range independently of HTTP."""
    if view_range is None:
        return 1, total_lines
    start, end = _parse_view_range(view_range)
    if not 1 <= start <= end:
        raise ValueError(f"invalid view_range [{start}, {end}] — must be 1-indexed with start <= end")
    if start > total_lines:
        raise ValueError(f"start line {start} exceeds file length ({total_lines} lines)")
    return start, min(end, total_lines)


def _write_new_content(target_path, content: str, encoding: str) -> tuple[int, str | None, int]:
    if encoding == "base64":
        import base64

        try:
            binary_content = base64.b64decode(content.strip(), validate=True)
        except ValueError:
            return 0, "invalid base64 content", 400
        return _write_binary_content(target_path, binary_content)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        return len(content.encode("utf-8")), None, 200
    except (OSError, UnicodeError):
        return 0, "Internal error", 500


def _write_binary_content(target_path, content: bytes) -> tuple[int, str | None, int]:
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
        return len(content), None, 200
    except OSError:
        return 0, "Internal error writing binary file", 500

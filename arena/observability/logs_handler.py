"""Bridge log tailing handler."""
from __future__ import annotations

from aiohttp import web

from arena.handler_context import RuntimeObservabilityHandlerContext

VALID_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _parse_log_query(request: web.Request) -> tuple[str, int]:
    try:
        level = request.query.get("level", "INFO").upper()
        lines_count = min(int(request.query.get("lines", "100")), 1000)
    except (ValueError, TypeError):
        level = "INFO"
        lines_count = 100
    if level not in VALID_LOG_LEVELS:
        level = "INFO"
    return level, lines_count


def _filter_log_lines(text: str, *, level: str, lines_count: int) -> list[str]:
    min_idx = VALID_LOG_LEVELS.index(level) if level in VALID_LOG_LEVELS else 1
    filter_levels = VALID_LOG_LEVELS[min_idx:]
    entries = [line for line in text.splitlines() if any(f" {lv} " in line for lv in filter_levels)]
    return entries[-lines_count:]


def make_logs_handler(ctx: RuntimeObservabilityHandlerContext):
    async def handle_v1_logs(request: web.Request) -> web.Response:
        """Return recent bridge log entries with optional level filter."""
        response = ctx.require_auth(request)
        if response:
            return response
        ctx.record_request()
        level, lines_count = _parse_log_query(request)

        log_entries: list[str] = []
        try:
            if ctx.log_file.exists():
                text = ctx.log_file.read_text(encoding="utf-8", errors="replace")
                log_entries = _filter_log_lines(text, level=level, lines_count=lines_count)
        except Exception as e:
            ctx.log_error("Failed to read log file: %s", e)

        return ctx.cors_json_response({
            "ok": True,
            "log_file": str(ctx.log_file),
            "level_filter": level,
            "lines": len(log_entries),
            "entries": log_entries,
        })

    return handle_v1_logs

"""Handlers for audit, request log, and webhooks.

v4.9.0: Added ``GET /v1/audit/stream`` -- NDJSON tail of the audit
log with optional live-follow, type-prefix filter and since-cursor.
Uses the same chunked-NDJSON machinery as /v1/exec/stream (v4.3.0)
so agents (and the future Audit tab live-tail toggle) can watch
new events arrive without polling ``/v1/audit?lines=...`` in a hot
loop.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import ObservabilityHandlerContext
from arena.handler_helpers import authed, err_json
from arena.http import CORS_HEADERS


@dataclass(frozen=True)
class ObservabilityHandlers:
    audit: object
    audit_stats: object
    audit_log: object
    webhooks_get: object
    webhooks_set: object
    # v4.9.0: chunked NDJSON tail of audit.jsonl.
    audit_stream: object


# v4.9.0 tunables. Deliberately conservative: 300s is long enough
# for interactive tab-open sessions, short enough that a forgotten
# agent connection can't hold a bridge worker forever. The poll
# interval balances "feels live" against "don't hammer inotify-less
# filesystems with fstat"; 500ms is what git/tail -F use by default.
_STREAM_MAX_DURATION_SEC = 300
_STREAM_POLL_INTERVAL_SEC = 0.5
_STREAM_MAX_LINES_HISTORY = 5000
_STREAM_READ_CHUNK = 64 * 1024


def _parse_stream_since(qs: dict[str, list[str]]) -> str | None:
    """Return the ``since=`` cursor if the caller passed one, else
    ``None``. Value is an opaque timestamp string -- we compare it
    against ``event["ts"]`` lexicographically because bridge audit
    timestamps are ISO-8601 UTC (which sort correctly as strings)."""
    val = (qs.get("since", [""])[0] or "").strip()
    return val or None


def _match_type_filter(event_type: str, prefix: str) -> bool:
    """Same semantics as the Audit tab's type filter: substring match
    so ``prefix="exec"`` catches every ``exec_*`` variant."""
    if not prefix:
        return True
    return prefix in (event_type or "")


def _tail_last_lines(path, n: int) -> list[str]:
    """Read the last ``n`` non-empty lines of a file, cheap-ish. We
    reuse the bridge's own ``read_tail`` via the context, but the
    streaming loop also needs to *seek* to the current EOF to
    start following -- that's what this helper is for. Returns
    lines without their trailing newline."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = min(size, 64 * 1024)
            fh.seek(size - block)
            data = fh.read(block)
    except OSError:
        return []
    lines = [ln for ln in data.decode("utf-8", "replace").splitlines() if ln.strip()]
    return lines[-n:] if len(lines) > n else lines


def make_observability_handlers(ctx: ObservabilityHandlerContext) -> ObservabilityHandlers:
    @authed(ctx)
    async def handle_v1_audit(request: web.Request) -> web.Response:
        qs = parse_qs(request.query_string)
        try:
            n = int(qs.get("lines", ["100"])[0])
        except ValueError:
            n = 100
        loop = asyncio.get_running_loop()
        lines = await loop.run_in_executor(ctx.executor, ctx.read_tail, ctx.audit_path, n)
        rows = []
        for line in lines:
            try:
                rows.append(json.loads(line))
            except Exception:
                rows.append({"raw": line})
        return ctx.cors_json_response({"ok": True, "lines": len(rows), "audit": str(ctx.audit_path), "events": rows})

    @authed(ctx)
    async def handle_v1_audit_stats(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.audit_stats_sync)
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_audit_log(request: web.Request) -> web.Response:
        try:
            lines_count = min(int(request.query.get("lines", "100")), 1000)
            method_filter = request.query.get("method", "").upper()
            path_filter = request.query.get("path", "")
            status_filter = request.query.get("status", "")
        except (ValueError, TypeError):
            lines_count = 100
            method_filter = ""
            path_filter = ""
            status_filter = ""
        entries = ctx.read_request_log(
            ctx.request_log_file,
            lines_count=lines_count,
            method_filter=method_filter,
            path_filter=path_filter,
            status_filter=status_filter,
        )
        return ctx.cors_json_response({
            "ok": True,
            "log_file": str(ctx.request_log_file),
            "filters": {"method": method_filter, "path": path_filter, "status": status_filter, "lines": lines_count},
            "count": len(entries),
            "entries": entries,
        })

    @authed(ctx)
    async def handle_v1_webhooks_get(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(ctx.executor, ctx.load_webhooks)
        return ctx.cors_json_response({"ok": True, "webhooks": data})

    @authed(ctx)
    async def handle_v1_webhooks_set(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return ctx.cors_json_response({"ok": False, "error": "invalid json"}, status=400)
        cfg, err = ctx.normalize_webhooks_config(data)
        if err:
            return ctx.cors_json_response({"ok": False, "error": err}, status=400)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(ctx.executor, ctx.save_webhooks, cfg)
        ctx.audit({"type": "webhooks_updated", "urls_count": len(cfg["urls"])})
        return ctx.cors_json_response({"ok": True, "webhooks": cfg})

    # v4.9.0: NDJSON audit tail with optional follow.
    @authed(ctx)
    async def handle_v1_audit_stream(request: web.Request) -> web.StreamResponse:
        qs = parse_qs(request.query_string)
        try:
            lines_hist = min(
                int(qs.get("lines", ["100"])[0]),
                _STREAM_MAX_LINES_HISTORY,
            )
        except (TypeError, ValueError):
            lines_hist = 100
        if lines_hist < 0:
            lines_hist = 0
        follow_raw = (qs.get("follow", ["0"])[0] or "").strip().lower()
        follow = follow_raw in {"1", "true", "yes", "on"}
        type_prefix = (qs.get("type", [""])[0] or "").strip()
        since = _parse_stream_since(qs)
        try:
            max_duration = min(
                int(qs.get("max_duration", [str(_STREAM_MAX_DURATION_SEC)])[0]),
                _STREAM_MAX_DURATION_SEC,
            )
        except (TypeError, ValueError):
            max_duration = _STREAM_MAX_DURATION_SEC
        if max_duration < 1:
            max_duration = 1

        # NDJSON transport headers -- same shape as /v1/exec/stream so
        # any client that already parses one can parse the other.
        headers = dict(CORS_HEADERS)
        headers["Content-Type"] = "application/x-ndjson"
        headers["Cache-Control"] = "no-cache"
        headers["X-Accel-Buffering"] = "no"
        response = web.StreamResponse(status=200, headers=headers)
        response.enable_chunked_encoding()
        await response.prepare(request)

        async def _emit(payload: dict) -> None:
            line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            await response.write(line)

        emitted = 0
        skipped = 0
        try:
            # Header event. Advertises what the client asked for so a
            # replayed capture is self-describing.
            await _emit({
                "type": "meta",
                "audit": str(ctx.audit_path),
                "follow": follow,
                "lines_history": lines_hist,
                "filters": {
                    "type_prefix": type_prefix or None,
                    "since": since,
                    "max_duration_sec": max_duration,
                },
                "server_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })

            # -------- history phase --------
            loop = asyncio.get_running_loop()
            if lines_hist > 0:
                hist_lines = await loop.run_in_executor(
                    ctx.executor, ctx.read_tail, ctx.audit_path, lines_hist,
                )
                for raw in hist_lines:
                    try:
                        event = json.loads(raw)
                    except Exception:
                        # Malformed lines still flow so operators can
                        # spot audit corruption during a follow session.
                        await _emit({"type": "raw", "line": raw})
                        emitted += 1
                        continue
                    ev_type = str(event.get("type") or "")
                    if not _match_type_filter(ev_type, type_prefix):
                        skipped += 1
                        continue
                    if since and str(event.get("ts") or "") <= since:
                        skipped += 1
                        continue
                    await _emit(event)
                    emitted += 1

            # -------- follow phase --------
            if follow:
                # Follow from current EOF so we don't re-emit history.
                try:
                    with open(str(ctx.audit_path), "rb") as fh:
                        fh.seek(0, os.SEEK_END)
                        pos = fh.tell()
                except OSError as e:
                    await _emit({"type": "error",
                                 "error": f"cannot open audit file: {e}"})
                    pos = None

                deadline = time.monotonic() + max_duration
                pending = b""
                while pos is not None and time.monotonic() < deadline:
                    try:
                        with open(str(ctx.audit_path), "rb") as fh:
                            fh.seek(pos)
                            data = fh.read(_STREAM_READ_CHUNK)
                            new_pos = fh.tell()
                    except OSError:
                        # File temporarily missing (log rotation, etc.)
                        # Sleep and retry from same offset.
                        await asyncio.sleep(_STREAM_POLL_INTERVAL_SEC)
                        continue

                    if data:
                        pos = new_pos
                        pending += data
                        while b"\n" in pending:
                            raw_bytes, _, pending = pending.partition(b"\n")
                            raw = raw_bytes.decode("utf-8", "replace").strip()
                            if not raw:
                                continue
                            try:
                                event = json.loads(raw)
                            except Exception:
                                await _emit({"type": "raw", "line": raw})
                                emitted += 1
                                continue
                            ev_type = str(event.get("type") or "")
                            if not _match_type_filter(ev_type, type_prefix):
                                skipped += 1
                                continue
                            if since and str(event.get("ts") or "") <= since:
                                skipped += 1
                                continue
                            await _emit(event)
                            emitted += 1
                    else:
                        # No new bytes -- sleep before next poll.
                        await asyncio.sleep(_STREAM_POLL_INTERVAL_SEC)

            # -------- terminal --------
            await _emit({
                "type": "exit",
                "reason": "max_duration" if follow else "history_only",
                "emitted": emitted,
                "skipped": skipped,
            })
        except asyncio.CancelledError:
            # Client dropped mid-stream. Still try to write a terminal
            # event so a well-behaved client sees a proper close.
            try:
                await _emit({"type": "exit", "reason": "client_disconnect",
                             "emitted": emitted, "skipped": skipped})
            except Exception:
                pass
            raise
        except Exception as e:  # noqa: BLE001
            try:
                await _emit({"type": "error", "error": repr(e)})
            except Exception:
                pass
        finally:
            try:
                await response.write_eof()
            except Exception:
                pass
        return response

    return ObservabilityHandlers(
        audit=handle_v1_audit,
        audit_stats=handle_v1_audit_stats,
        audit_log=handle_v1_audit_log,
        webhooks_get=handle_v1_webhooks_get,
        webhooks_set=handle_v1_webhooks_set,
        audit_stream=handle_v1_audit_stream,
    )

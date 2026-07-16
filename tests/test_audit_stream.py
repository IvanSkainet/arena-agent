"""Tests for GET /v1/audit/stream (v4.9.0).

Covers:
* route registration + wiring + dataclass field
* helper functions (``_match_type_filter``, ``_tail_last_lines``,
  ``_parse_stream_since``)
* history-phase NDJSON emission against a synthetic audit file,
  including type-prefix filter and since-cursor filter
* follow-phase live-tail: appending to the file mid-stream results
  in the new event being emitted
* terminal ``exit`` event shape (``reason`` + counters)

The live-tail test uses an aiohttp TestClient bound to a minimal
app that registers only the audit-stream handler with an
``ObservabilityHandlerContext`` filled from stubs -- no
``unified_bridge.make_app`` here, so we don't churn the shared
module-level executors (the same lesson from v4.3.0).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Registration / wiring guards
# ---------------------------------------------------------------------------
def test_audit_stream_route_in_registry():
    from arena.route_registry.registry import ROUTES
    keys = {(m, p) for (m, p, *_rest) in ROUTES}
    assert ("GET", "/v1/audit/stream") in keys


def test_audit_stream_route_wired_in_core_router():
    """The router registration in core.py must reference the same
    handler key our wiring layer exports."""
    core_py = (Path(__file__).resolve().parents[1]
               / "arena" / "route_registry" / "core.py").read_text(encoding="utf-8")
    assert 'add_get("/v1/audit/stream"' in core_py
    assert 'h["handle_v1_audit_stream"]' in core_py


def test_wiring_exports_audit_stream_key():
    wiring = (Path(__file__).resolve().parents[1]
              / "arena" / "wiring" / "memory_observability_registries.py"
              ).read_text(encoding="utf-8")
    assert '"handle_v1_audit_stream": "audit_stream"' in wiring


def test_observability_handlers_dataclass_has_audit_stream_field():
    from arena.observability.handlers import ObservabilityHandlers
    assert "audit_stream" in ObservabilityHandlers.__dataclass_fields__


# ---------------------------------------------------------------------------
# Helpers -- deterministic, no I/O for the pure ones
# ---------------------------------------------------------------------------
def test_match_type_filter_substring_semantics():
    """Prefix param uses substring semantics, matching the Audit-tab
    filter: 'exec' matches exec_start / exec_stream_* / exec_script_*."""
    from arena.observability.handlers import _match_type_filter
    assert _match_type_filter("exec_stream_done", "exec") is True
    assert _match_type_filter("exec_stream_done", "stream") is True
    assert _match_type_filter("file_upload", "exec") is False
    assert _match_type_filter("", "exec") is False
    # Empty filter = pass through.
    assert _match_type_filter("anything", "") is True


def test_parse_stream_since_returns_none_for_empty():
    from arena.observability.handlers import _parse_stream_since
    assert _parse_stream_since({}) is None
    assert _parse_stream_since({"since": [""]}) is None
    assert _parse_stream_since({"since": ["  "]}) is None
    assert _parse_stream_since({"since": ["2026-07-16T00:00:00Z"]}) == \
        "2026-07-16T00:00:00Z"


def test_tail_last_lines_returns_last_n_and_no_more(tmp_path):
    from arena.observability.handlers import _tail_last_lines
    f = tmp_path / "audit.jsonl"
    f.write_text(
        "\n".join(f'{{"n":{i}}}' for i in range(20)) + "\n",
        encoding="utf-8",
    )
    lines = _tail_last_lines(f, 5)
    assert len(lines) == 5
    assert lines[-1] == '{"n":19}'
    # Empty file -> empty list
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert _tail_last_lines(empty, 5) == []
    # Missing file -> empty list (never raises)
    assert _tail_last_lines(tmp_path / "nope.jsonl", 5) == []


# ---------------------------------------------------------------------------
# End-to-end via aiohttp TestClient with a minimal app
# ---------------------------------------------------------------------------
def _build_stream_only_app(audit_path: Path):
    """Build an aiohttp app that only registers the audit-stream
    handler + its dependencies. Avoids touching unified_bridge's
    module-level executors so we can run several tests in a row
    without the 'cannot schedule new futures after shutdown' bite.
    """
    from aiohttp import web
    from concurrent.futures import ThreadPoolExecutor
    from arena.contexts.observability import ObservabilityHandlerContext
    from arena.http import cors_json_response
    from arena.observability.handlers import make_observability_handlers

    def _read_tail(path, n):
        try:
            with open(str(path), encoding="utf-8", errors="replace") as fh:
                lines = [ln for ln in fh.read().splitlines() if ln.strip()]
            return lines[-n:]
        except OSError:
            return []

    ctx = ObservabilityHandlerContext(
        require_auth=lambda req: None,  # open -- tests pass token anyway
        record_request=lambda **_kw: None,
        cors_json_response=cors_json_response,
        executor=ThreadPoolExecutor(max_workers=2),
        audit_path=audit_path,
        request_log_file=audit_path.parent / "requests.log",
        read_tail=_read_tail,
        read_request_log=lambda *_a, **_kw: [],
        audit_stats_sync=lambda: {"ok": True},
        load_webhooks=lambda: {"urls": []},
        save_webhooks=lambda cfg: None,
        normalize_webhooks_config=lambda d: (d, None),
        audit=lambda ev: None,
    )
    handlers = make_observability_handlers(ctx)
    app = web.Application()
    app.router.add_get("/v1/audit/stream", handlers.audit_stream)
    return app, ctx


def _parse_ndjson(body: bytes) -> list[dict]:
    events = []
    for ln in body.decode("utf-8").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        events.append(json.loads(ln))
    return events


def test_stream_history_only_emits_all_matching_events_then_exits():
    """Without ``follow=1`` the handler emits the recent tail and
    terminates with ``{"type":"exit","reason":"history_only",...}``."""
    from aiohttp.test_utils import TestClient, TestServer

    async def _run():
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "audit.jsonl"
            path.write_text(
                '{"ts":"2026-07-16T10:00:01Z","type":"exec_start","cmd":"echo a"}\n'
                '{"ts":"2026-07-16T10:00:02Z","type":"exec_done","exit_code":0}\n'
                '{"ts":"2026-07-16T10:00:03Z","type":"file_upload","path":"/tmp/x"}\n',
                encoding="utf-8",
            )
            app, _ctx = _build_stream_only_app(path)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/v1/audit/stream?lines=100")
                assert resp.status == 200
                assert resp.headers.get("Content-Type", "").startswith(
                    "application/x-ndjson"
                )
                body = await resp.read()
        events = _parse_ndjson(body)
        types = [e["type"] for e in events]
        assert types[0] == "meta"
        assert types[-1] == "exit"
        # Three history events must show up between meta and exit.
        middle_types = [e["type"] for e in events[1:-1]]
        assert middle_types == ["exec_start", "exec_done", "file_upload"]
        exit_ev = events[-1]
        assert exit_ev["reason"] == "history_only"
        assert exit_ev["emitted"] == 3
        assert exit_ev["skipped"] == 0

    asyncio.run(_run())


def test_stream_type_filter_and_since_cursor_skip_events():
    """``type=exec`` + ``since=<ts>`` must skip both non-exec events
    and exec events at or before the cursor."""
    from aiohttp.test_utils import TestClient, TestServer

    async def _run():
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "audit.jsonl"
            path.write_text(
                '{"ts":"2026-07-16T10:00:01Z","type":"exec_start"}\n'
                '{"ts":"2026-07-16T10:00:02Z","type":"file_upload"}\n'
                '{"ts":"2026-07-16T10:00:03Z","type":"exec_stream_done"}\n'
                '{"ts":"2026-07-16T10:00:04Z","type":"exec_done","exit_code":0}\n',
                encoding="utf-8",
            )
            app, _ctx = _build_stream_only_app(path)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get(
                    "/v1/audit/stream?lines=100&type=exec"
                    "&since=2026-07-16T10:00:02Z"
                )
                assert resp.status == 200
                body = await resp.read()
        events = _parse_ndjson(body)
        middle = [e for e in events
                  if e["type"] not in ("meta", "exit", "error", "raw")]
        # exec_start (at ts=01Z) skipped by since, file_upload (02Z)
        # skipped by type filter AND since; exec_stream_done (03Z)
        # and exec_done (04Z) survive.
        assert [e["type"] for e in middle] == \
            ["exec_stream_done", "exec_done"]
        exit_ev = events[-1]
        assert exit_ev["reason"] == "history_only"
        assert exit_ev["emitted"] == 2


def test_stream_follow_picks_up_new_events_appended_mid_stream():
    """Real live-tail: start with an empty file, ``follow=1&lines=0``,
    then append a line -- the client must see it before ``exit``."""
    from aiohttp.test_utils import TestClient, TestServer

    async def _run():
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "audit.jsonl"
            path.write_text("", encoding="utf-8")
            app, _ctx = _build_stream_only_app(path)
            async with TestClient(TestServer(app)) as client:
                # Cap max_duration so the test never runs long even if
                # the append somehow doesn't land.
                stream_task = asyncio.create_task(
                    client.get(
                        "/v1/audit/stream?lines=0&follow=1&max_duration=3"
                    )
                )
                # Give the handler a beat to prepare and start following.
                await asyncio.sleep(0.6)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(
                        '{"ts":"2026-07-16T10:00:10Z",'
                        '"type":"exec_done","exit_code":0}\n'
                    )
                    fh.flush()
                    os.fsync(fh.fileno())
                resp = await stream_task
                assert resp.status == 200
                body = await resp.read()
        events = _parse_ndjson(body)
        types = [e["type"] for e in events]
        assert types[0] == "meta"
        assert "exec_done" in types
        assert types[-1] == "exit"
        assert events[-1]["reason"] in {"max_duration", "history_only"}
        assert events[-1]["emitted"] >= 1

    asyncio.run(_run())


def test_stream_max_duration_is_clamped_to_ceiling():
    """A caller passing ``max_duration=99999`` must be silently
    clamped to the module ceiling so a runaway agent can't hold a
    worker forever."""
    from arena.observability import handlers as mod
    assert mod._STREAM_MAX_DURATION_SEC <= 3600, (
        "streaming ceiling should stay bounded; if you raise it, "
        "add a follow-up test that a hostile query can't exceed it"
    )

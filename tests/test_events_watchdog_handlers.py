"""Realtime events and watchdog handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.events.handlers import make_event_handlers  # noqa: E402
from arena.events.runtime import EVENT_SUBSCRIBERS  # noqa: E402
from arena.handler_context import EventHandlerContext, WatchdogHandlerContext  # noqa: E402
from arena.watchdog.handlers import make_watchdog_handlers  # noqa: E402
from arena.watchdog.runtime import WATCHDOG_STATE  # noqa: E402


def test_events_and_watchdog_reexported_for_compatibility():
    assert ub._event_subscribers is EVENT_SUBSCRIBERS
    assert ub._watchdog_state is WATCHDOG_STATE


def test_event_handlers_factory_outputs():
    ctx = EventHandlerContext(
        require_auth=ub.require_auth,
        version=ub.VERSION,
        utc_now=ub.utc_now,
        log_info=ub.log.info,
    )
    handlers = make_event_handlers(ctx)
    assert callable(handlers.events)


def test_watchdog_handlers_factory_outputs():
    ctx = WatchdogHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        metrics=ub.BRIDGE_METRICS,
        now=lambda: ub.BRIDGE_METRICS["start_time"] + 1.0,
        log_info=ub.log.info,
    )
    handlers = make_watchdog_handlers(ctx)
    assert callable(handlers.watchdog)


def test_events_watchdog_routes_registered():
    app = ub.make_app({
        "token": "test",
        "profile": "owner-shell",
        "root": Path("/tmp"),
        "active_exec": 0,
        "max_concurrent": 3,
        "audit": "audit",
        "timeout": 60,
        "max_timeout": 3600,
        "max_output": 2000000,
        "allow_any_cwd": False,
        "semaphore": asyncio.Semaphore(1),
    })
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/events") in paths
    assert ("GET", "/v1/watchdog") in paths
    assert ("POST", "/v1/watchdog") in paths


def test_emit_event_drops_full_subscribers():
    q = asyncio.Queue(maxsize=1)
    q.put_nowait({"already": "full"})
    EVENT_SUBSCRIBERS.append(q)
    try:
        asyncio.run(ub.emit_event("unit", {"ok": True}))
        assert q not in EVENT_SUBSCRIBERS
    finally:
        if q in EVENT_SUBSCRIBERS:
            EVENT_SUBSCRIBERS.remove(q)

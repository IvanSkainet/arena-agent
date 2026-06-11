"""Alert handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import AlertsHandlerContext  # noqa: E402
from arena.observability.alerts import ALERTS_CONFIG, make_alert_handlers  # noqa: E402


def test_alert_config_reexported_for_compatibility():
    assert "high_latency" in ALERTS_CONFIG
    assert ub._ALERTS_CONFIG is ALERTS_CONFIG


def test_alert_handlers_factory_outputs():
    ctx = AlertsHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        metrics=ub.BRIDGE_METRICS,
        watchdog_state=ub._watchdog_state,
        cdp_state=ub._cdp_state,
        rate_limit_lock=ub._rate_limit_lock,
        rate_limit_store=ub._rate_limit_store,
        rate_limit_window=ub._rate_limit_window,
        rate_limit_max=ub._rate_limit_max,
        now=lambda: ub.BRIDGE_METRICS["start_time"] + 1.0,
        log_info=ub.log.info,
    )
    handlers = make_alert_handlers(ctx)
    assert callable(handlers.alerts)


def test_alert_routes_registered():
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
    assert ("GET", "/v1/alerts") in paths
    assert ("POST", "/v1/alerts") in paths

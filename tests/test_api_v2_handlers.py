"""API v2 compatibility handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.api_v2.handlers import DEPRECATED_ENDPOINTS, cfg_get_max_timeout, make_v2_handlers  # noqa: E402
from arena.handler_context import ApiV2HandlerContext  # noqa: E402


def _ctx(tmp_path: Path) -> ApiV2HandlerContext:
    return ApiV2HandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        version=ub.VERSION,
        metrics=ub.BRIDGE_METRICS,
        cdp_state=ub._cdp_state,
        watchdog_state=ub._watchdog_state,
        cluster_state=ub._cluster_state,
        cluster_config=ub._cluster_config,
        tls_config=ub._tls_config,
        profiles_dir=tmp_path,
        sandbox_config=ub._sandbox_config,
        blocked_reason=ub.blocked_reason,
        first_word=ub.first_word,
        decode_output=ub.decode_output,
        run_sandboxed=ub._run_sandboxed,
        cfg_get_max_timeout=ub.cfg_get_max_timeout,
        audit=ub.audit,
        emit_event=ub.emit_event,
        now=lambda: ub.BRIDGE_METRICS["start_time"] + 1.25,
    )


def test_api_v2_deprecated_endpoints_exported_for_middleware():
    assert DEPRECATED_ENDPOINTS["/v1/service/info"]["replacement"] == "/v1/status"
    assert ub._DEPRECATED_ENDPOINTS is DEPRECATED_ENDPOINTS


def test_api_v2_handlers_factory_outputs(tmp_path):
    handlers = make_v2_handlers(_ctx(tmp_path))
    assert callable(handlers.index)
    assert callable(handlers.status)
    assert callable(handlers.health)
    assert callable(handlers.browser_status)
    assert callable(handlers.exec)
    assert callable(handlers.deprecations)


def test_api_v2_routes_registered():
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
    assert ("GET", "/v2/") in paths
    assert ("GET", "/v2/status") in paths
    assert ("GET", "/v2/health") in paths
    assert ("GET", "/v2/browser/status") in paths
    assert ("POST", "/v2/exec") in paths
    assert ("GET", "/v2/deprecations") in paths


def test_api_v2_cfg_get_max_timeout_default():
    assert cfg_get_max_timeout(object()) == 600

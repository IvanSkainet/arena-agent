"""Browser session profile handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import ProfileHandlerContext  # noqa: E402
from arena.profiles.handlers import PROFILES_DIR, ensure_profiles_dir, make_profile_handlers  # noqa: E402


def test_profiles_dir_reexported_for_compatibility():
    assert ub._PROFILES_DIR is PROFILES_DIR
    assert ub._ensure_profiles_dir() == ensure_profiles_dir()


def test_profile_handlers_factory_outputs():
    ctx = ProfileHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        profiles_dir=ub._PROFILES_DIR,
        ensure_profiles_dir=ub._ensure_profiles_dir,
        cdp_state=ub._cdp_state,
        cdp_active_tab=lambda *args, **kwargs: ub._cdp_active_tab(*args, **kwargs),
        version=ub.VERSION,
        utc_now=ub.utc_now,
        audit=ub.audit,
        emit_event=ub.emit_event,
        log_warning=ub.log.warning,
    )
    handlers = make_profile_handlers(ctx)
    assert callable(handlers.profiles)
    assert callable(handlers.load)


def test_profile_routes_registered():
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
    assert ("GET", "/v1/profiles") in paths
    assert ("POST", "/v1/profiles") in paths
    assert ("POST", "/v1/profiles/{name}/load") in paths

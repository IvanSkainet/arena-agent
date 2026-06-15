"""Bridge composition container tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.container import BridgeContainer, build_container, build_handler_registry  # noqa: E402


def test_build_handler_registry_filters_legacy_handler_globals():
    def handle_v1_test():
        pass

    def handle_health():
        pass

    def not_a_handler():
        pass

    registry = build_handler_registry({
        "handle_v1_test": handle_v1_test,
        "handle_health": handle_health,
        "not_a_handler": not_a_handler,
        "handle_v1_not_callable": object(),
    })
    assert registry == {"handle_v1_test": handle_v1_test, "handle_health": handle_health}


def test_build_container_returns_handler_registry():
    container = build_container(ub.__dict__)
    assert isinstance(container, BridgeContainer)
    assert "handle_health" in container.handlers
    assert "handle_v1_status" in container.handlers
    assert "handle_mcp_post" in container.handlers
    assert "not_a_real_handler" not in container.handlers


def test_unified_make_app_uses_container_and_routes():
    assert ub.build_container is build_container
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
    assert ("GET", "/health") in paths
    assert ("POST", "/mcp") in paths



def test_build_public_handlers_from_container():
    from arena.container import PublicWiringContext, build_public_handlers

    registry = build_public_handlers(PublicWiringContext(
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        metrics=ub.BRIDGE_METRICS,
        version=ub.VERSION,
        now=lambda: ub.BRIDGE_METRICS["start_time"] + 1,
        hostname=lambda: "unit-host",
        bridge_port=lambda: 8765,
    ))
    assert set(registry) == {"handle_index", "handle_health", "handle_api_docs"}
    assert registry["handle_health"].__module__ == "arena.public.handlers"


def test_build_system_service_admin_handlers_from_container(tmp_path):
    from arena.container import (
        AdminWiringContext,
        ServiceWiringContext,
        SystemWiringContext,
        build_admin_handlers,
        build_service_handlers,
        build_system_handlers,
    )

    system = build_system_handlers(SystemWiringContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        common_status=lambda cfg: {"ok": True},
        version="test",
        clean_platform_name=lambda: "platform",
        doctor_sync=lambda token: {"ok": True},
        sysinfo_sync=lambda root: {"ok": True},
        play_beep_sync=lambda beep_type, freq, dur: {"ok": True},
    ))
    assert "handle_v1_status" in system
    assert system["handle_v1_status"].__module__ == "arena.system.handlers"

    service = build_service_handlers(ServiceWiringContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        service_info_sync=lambda: {"ok": True},
        sys_svc_sync=lambda: {"ok": True},
        capabilities_sync=lambda: {"ok": True},
        spawn_respawn_helper=lambda delay: (True, "ok"),
        audit=lambda event: None,
    ))
    assert "handle_v1_capabilities" in service
    assert service["handle_v1_restart"].__module__ == "arena.service.handlers"

    admin = build_admin_handlers(AdminWiringContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        audit=lambda event: None,
        default_token_file=tmp_path / "token.txt",
        root_agent=tmp_path,
        subprocess_kwargs=lambda: {},
    ))
    assert "handle_v1_sys_funnel" in admin
    assert admin["handle_v1_token_regenerate"].__module__ == "arena.admin.handlers"

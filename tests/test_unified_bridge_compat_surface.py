"""Compatibility surface tests for the thin unified_bridge.py facade."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402


EXPECTED_CALLABLES = [
    "make_app",
    "serve",
    "main",
    "check_auth",
    "require_auth",
    "_inventory_sync",
    "_hardware_from_inventory_sync",
    "_spawn_respawn_helper",
    "_service_info_sync",
    "_sys_svc_sync",
    "_skills_run_sync",
    "_tasks_list_sync",
    "_recall_sync",
    "_cdp_active_tab",
    "_ensure_cookie_manager",
    "handle_v1_exec",
    "handle_v1_cdp_status",
    "handle_v1_desktop_windows",
    "handle_v1_service_info",
    "handle_v2_status",
    "handle_mcp_post",
    "handle_gateway_tools",
]

EXPECTED_OBJECTS = [
    "VERSION",
    "APP_DIR",
    "BRIDGE_DIR",
    "TOKEN_FILE",
    "AUDIT",
    "MCP_TOOLS",
    "_cdp_state",
    "_control_state",
    "BRIDGE_METRICS",
    "CAUTIOUS_ALLOW",
]


def test_unified_bridge_exports_expected_callable_compat_names():
    missing = [name for name in EXPECTED_CALLABLES if not callable(getattr(ub, name, None))]
    assert missing == []


def test_unified_bridge_exports_expected_object_compat_names():
    missing = [name for name in EXPECTED_OBJECTS if not hasattr(ub, name)]
    assert missing == []


def test_unified_bridge_version_matches_constants():
    from arena.constants import VERSION

    assert ub.VERSION == VERSION


def test_unified_bridge_app_factory_still_registers_routes():
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
    })
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/health") in paths
    assert ("POST", "/v1/exec") in paths
    assert ("GET", "/v1/cdp/status") in paths
    assert ("POST", "/mcp") in paths

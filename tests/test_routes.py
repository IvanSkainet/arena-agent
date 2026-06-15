"""Route registry extraction tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.routes import register_routes  # noqa: E402


def test_unified_make_app_uses_extracted_route_registry():
    assert ub.register_routes is register_routes


def test_route_registry_registers_core_and_cdp_routes():
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
    assert ("POST", "/v1/exec") in paths
    assert ("GET", "/v1/browser/cdp/status") in paths
    assert ("GET", "/v1/cdp/status") in paths
    assert ("POST", "/mcp") in paths
    assert ("GET", "/gateway/tools") in paths
    assert ("GET", "/v2/status") in paths

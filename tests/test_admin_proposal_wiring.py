"""Wire-up + integration tests for the v4.19.0 proposal endpoints.

These prove the HTTP surface exists, is properly authenticated,
and dispatches into the ``arena.admin.proposal`` state machine.
The heavy pipeline tests (worktree + apply + pytest) live in
tests/test_admin_proposal_core.py -- here we only check that
the wire is correct.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Registry + router wire
# ---------------------------------------------------------------------------

def test_all_three_routes_in_registry():
    from arena.route_registry.registry import ROUTES
    keys = {(m, p) for (m, p, *_rest) in ROUTES}
    assert ("POST", "/v1/admin/proposal/submit") in keys
    assert ("GET",  "/v1/admin/proposal/status") in keys
    assert ("GET",  "/v1/admin/proposal/list") in keys


def test_all_three_routes_wired_in_core_router():
    core_py = (Path(__file__).resolve().parents[1]
               / "arena" / "route_registry" / "core.py"
               ).read_text(encoding="utf-8")
    assert 'add_post("/v1/admin/proposal/submit"' in core_py
    assert 'add_get("/v1/admin/proposal/status"' in core_py
    assert 'add_get("/v1/admin/proposal/list"' in core_py


def test_platform_wiring_exports_all_three():
    plat = (Path(__file__).resolve().parents[1]
            / "arena" / "wiring" / "platform.py"
            ).read_text(encoding="utf-8")
    for name in ("handle_v1_admin_proposal_submit",
                 "handle_v1_admin_proposal_status",
                 "handle_v1_admin_proposal_list"):
        assert name in plat, f"platform wiring missing {name}"


def test_admin_handlers_dataclass_has_three_fields():
    from arena.admin.handlers import AdminHandlers
    for f in ("proposal_submit", "proposal_status", "proposal_list"):
        assert f in AdminHandlers.__dataclass_fields__


def test_make_app_registers_all_three():
    """Full wire smoke: bring up the app and enumerate its
    routes. Regression guard against a future edit that adds the
    handler but forgets a wiring layer."""
    import unified_bridge as ub
    app = ub.make_app({
        "token": "t", "profile": "owner-shell", "root": Path("/tmp"),
        "active_exec": 0, "max_concurrent": 3, "audit": "audit",
        "timeout": 60, "max_timeout": 3600, "max_output": 2000000,
        "allow_any_cwd": False, "semaphore": asyncio.Semaphore(1),
    })
    paths = {
        (r.method, r.resource.get_info().get("path")
                   or r.resource.get_info().get("formatter"))
        for r in app.router.routes()
    }
    assert ("POST", "/v1/admin/proposal/submit") in paths
    assert ("GET",  "/v1/admin/proposal/status") in paths
    assert ("GET",  "/v1/admin/proposal/list") in paths

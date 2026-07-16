"""Exec handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.exec.handlers import make_exec_handlers  # noqa: E402
from arena.handler_context import ExecHandlerContext  # noqa: E402


def test_exec_handlers_factory_outputs():
    ctx = ExecHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        audit=ub.audit,
        blocked_reason=ub.blocked_reason,
        control_check=ub._control_check,
        is_input_injection_cmd=ub._is_input_injection_cmd,
        first_word=ub.first_word,
        under_root=ub.under_root,
        decode_output=ub.decode_output,
        run_shell_command=ub.run_shell_command,
        active_processes=ub.ACTIVE_PROCESSES,
        active_processes_snapshot=ub.active_processes_snapshot,
        cautious_allow=ub.CAUTIOUS_ALLOW,
        default_max_output=ub.DEFAULT_MAX_OUTPUT,
    )
    handlers = make_exec_handlers(ctx)
    assert callable(handlers.ps)
    assert callable(handlers.exec)
    assert callable(handlers.kill)


def test_exec_routes_registered():
    app = ub.make_app({"token": "test", "profile": "owner-shell", "root": Path("/tmp"), "active_exec": 0, "max_concurrent": 3, "audit": "audit", "timeout": 60, "max_timeout": 3600, "max_output": 2000000, "allow_any_cwd": False, "semaphore": asyncio.Semaphore(1)})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/ps") in paths
    assert ("POST", "/v1/exec") in paths
    assert ("POST", "/v1/kill") in paths


# --- v3.94.0 migration regression guards ---------------------------------

def test_exec_handlers_use_authed_decorator():
    """v3.94.0: All 3 exec handlers must be wrapped by @authed. `exec`
    and `kill` use auto_record=False (they do their own accounting),
    but functools.wraps still sets __wrapped__."""
    import unified_bridge as ub
    ctx = ExecHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        audit=ub.audit,
        blocked_reason=ub.blocked_reason,
        control_check=ub._control_check,
        is_input_injection_cmd=ub._is_input_injection_cmd,
        first_word=ub.first_word,
        under_root=ub.under_root,
        decode_output=ub.decode_output,
        run_shell_command=ub.run_shell_command,
        active_processes=ub.ACTIVE_PROCESSES,
        active_processes_snapshot=ub.active_processes_snapshot,
        cautious_allow=ub.CAUTIOUS_ALLOW,
        default_max_output=ub.DEFAULT_MAX_OUTPUT,
    )
    handlers = make_exec_handlers(ctx)
    for name in ("ps", "exec", "kill"):
        h = getattr(handlers, name)
        assert hasattr(h, "__wrapped__"), (
            f"exec handler `{name}` is not wrapped by @authed — "
            f"v3.94.0 migration expects all exec handlers to use "
            f"arena.handler_helpers.authed."
        )


def test_exec_handlers_module_free_of_manual_auth_prelude():
    """v3.94.0: Confirm the inline `ctx.require_auth(request); if r: return r`
    prelude has been removed from arena.exec.handlers."""
    import inspect
    from arena.exec import handlers as _exh
    src = inspect.getsource(_exh)
    assert "r = ctx.require_auth(request)" not in src, (
        "arena/exec/handlers.py still contains the inline auth "
        "prelude — v3.94.0 migrated it to @authed."
    )

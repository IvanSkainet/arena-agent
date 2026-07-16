"""Tests for POST /v1/exec/script (v4.2.0)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402


def test_exec_script_route_in_registry():
    from arena.route_registry.registry import ROUTES
    keys = {(m, p) for (m, p, *_rest) in ROUTES}
    assert ("POST", "/v1/exec/script") in keys


def test_exec_script_route_wired_into_app():
    app = ub.make_app({
        "token": "test", "profile": "owner-shell", "root": Path("/tmp"),
        "active_exec": 0, "max_concurrent": 3, "audit": "audit",
        "timeout": 60, "max_timeout": 3600, "max_output": 2000000,
        "allow_any_cwd": False, "semaphore": asyncio.Semaphore(1),
    })
    paths = {
        (r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter"))
        for r in app.router.routes()
    }
    assert ("POST", "/v1/exec/script") in paths


def test_exec_handlers_factory_exposes_script():
    """Regression guard: the script handler is exported on ExecHandlers
    so wiring can pick it up via export_handler_attrs."""
    from arena.exec.handlers import make_exec_handlers, ExecHandlers
    from arena.handler_context import ExecHandlerContext
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
    assert callable(handlers.script)
    # And @authed-wrapped (v3.94.0 migration).
    assert hasattr(handlers.script, "__wrapped__")


def test_interpreter_table_covers_common_shells():
    """Contract test — agents rely on these keys being available."""
    from arena.exec.handlers import _INTERPRETERS
    for expected in ("bash", "sh", "python", "python3", "node",
                     "pwsh", "powershell"):
        assert expected in _INTERPRETERS, f"missing interpreter: {expected}"


def test_resolve_interpreter_defaults_by_platform():
    import os
    from arena.exec.handlers import _resolve_interpreter
    resolved = _resolve_interpreter("")
    assert resolved is not None
    name, cfg = resolved
    if os.name == "nt":
        assert name == "powershell"
    else:
        assert name == "bash"


def test_resolve_interpreter_rejects_unknown():
    from arena.exec.handlers import _resolve_interpreter
    assert _resolve_interpreter("perl6") is None
    assert _resolve_interpreter("ruby") is None
    # Case-insensitive matching.
    resolved = _resolve_interpreter("BASH")
    assert resolved and resolved[0] == "bash"


def test_interpreter_cmd_uses_safe_flags():
    """bash script mode should propagate errors (errexit), fail on
    undefined vars (nounset), and stop pipelines on first-command
    failure (pipefail) — combined as ``-euo pipefail``. Prevents
    a typo'd $FOO from running silently with an empty value.
    """
    from arena.exec.handlers import _INTERPRETERS
    bash_cmd = str(_INTERPRETERS["bash"]["cmd"])
    # `-euo pipefail` is a single-arg form that includes all three;
    # accept either the combined shorthand or the split flags.
    assert "-euo pipefail" in bash_cmd or (
        "-e" in bash_cmd.split() and
        "-u" in bash_cmd.split() and
        "pipefail" in bash_cmd
    ), f"bash cmd missing safe flags: {bash_cmd!r}"
    # PowerShell should disable profile so agent scripts don't get
    # random modules loaded from the operator's $PROFILE.
    assert "-NoProfile" in _INTERPRETERS["pwsh"]["cmd"]
    assert "-NoProfile" in _INTERPRETERS["powershell"]["cmd"]

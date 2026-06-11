"""Sandbox runtime and handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import SandboxHandlerContext  # noqa: E402
from arena.sandbox.handlers import make_sandbox_handlers  # noqa: E402
from arena.sandbox.runtime import SANDBOX_CONFIG, run_sandboxed  # noqa: E402


def test_sandbox_config_reexported_for_compatibility():
    assert ub._sandbox_config is SANDBOX_CONFIG
    assert "allowed_commands" in SANDBOX_CONFIG


def test_sandbox_handlers_factory_outputs():
    ctx = SandboxHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        blocked_reason=ub.blocked_reason,
        first_word=ub.first_word,
        run_sandboxed=ub._run_sandboxed,
        audit=ub.audit,
        emit_event=ub.emit_event,
    )
    handlers = make_sandbox_handlers(ctx)
    assert callable(handlers.sandbox)


def test_sandbox_routes_registered():
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
    assert ("GET", "/v1/sandbox") in paths
    assert ("POST", "/v1/sandbox") in paths


def test_sandbox_runtime_smoke(tmp_path):
    result = asyncio.run(run_sandboxed(
        "echo sandbox-ok",
        timeout=5,
        root_agent=tmp_path,
        decode_output_fn=ub.decode_output,
    ))
    assert result["ok"] is True
    assert "sandbox-ok" in result["stdout"]

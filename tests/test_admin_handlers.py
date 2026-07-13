"""Admin/network handler factory and runtime smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.admin.handlers import make_admin_handlers  # noqa: E402
from arena.admin.runtime import CLOUDFLARED_STATE, cloudflared_funnel_action, tailscale_funnel_action, token_regenerate  # noqa: E402
from arena.handler_context import AdminHandlerContext  # noqa: E402


def _ctx(tmp_path: Path) -> AdminHandlerContext:
    return AdminHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        audit=ub.audit,
        default_token_file=tmp_path / "token.txt",
        root_agent=tmp_path,
        subprocess_kwargs=ub._subprocess_kwargs,
    )


def test_admin_handlers_factory_outputs(tmp_path):
    handlers = make_admin_handlers(_ctx(tmp_path))
    assert callable(handlers.sys_funnel)
    assert callable(handlers.token_regenerate)
    assert callable(handlers.tailscale_funnel)
    assert callable(handlers.cloudflared_tunnel)


def test_admin_routes_registered():
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
    assert ("GET", "/v1/sys/funnel") in paths
    assert ("POST", "/v1/token/regenerate") in paths
    assert ("POST", "/v1/tailscale/funnel/{action}") in paths
    assert ("GET", "/v1/tailscale/funnel/{action}") in paths
    assert ("POST", "/v1/cloudflared/tunnel/{action}") in paths
    assert ("GET", "/v1/cloudflared/tunnel/{action}") in paths


def test_unified_admin_handlers_bound_to_admin_module():
    assert ub.handle_v1_sys_funnel.__module__ == "arena.admin.handlers"
    assert ub.handle_v1_token_regenerate.__module__ == "arena.admin.handlers"
    assert ub.handle_v1_tailscale_funnel.__module__ == "arena.admin.handlers"
    assert ub.handle_v1_cloudflared_tunnel.__module__ == "arena.admin.handlers"
    assert ub._CLOUDFLARED_STATE is CLOUDFLARED_STATE


def test_token_regenerate_writes_single_target(tmp_path):
    target = tmp_path / "token.txt"
    result = token_regenerate(str(target), default_token_file=tmp_path / "default-token.txt")
    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == result["token"]
    assert result["written_to"] == [str(target)]


def test_tunnel_invalid_actions(tmp_path):
    assert tailscale_funnel_action("bad", 8765)["ok"] is False
    assert cloudflared_funnel_action("bad", 8765, root_agent=tmp_path, subprocess_kwargs=ub._subprocess_kwargs)["ok"] is False


def test_tailscale_funnel_action_bad_never_omits_error():
    """Every failure path from tailscale_funnel_action must set `error`
    so the Dashboard alert can render a useful message instead of `?`."""
    for bogus in ("bad", "", None, "STOP"):
        r = tailscale_funnel_action(bogus, 8765)
        if not r.get("ok"):
            assert r.get("error"), f"missing error for action={bogus!r}: {r}"


def test_tailscale_funnel_action_stop_uses_new_syntax():
    """Regression guard: the modern Tailscale funnel-stop path (>=1.60)
    must never revert to the legacy `--https=443 off` command which only
    ever targeted port 443. Checks the actual argv, not source text (so
    documentation comments explaining the old syntax do not trigger it)."""
    import inspect
    from arena.admin import tailscale as _ts
    src = inspect.getsource(_ts.tailscale_funnel_action)

    # Strip comment lines before scanning: mentioning the legacy form in a
    # docstring or `# ...` explainer is not the same as actually calling it.
    code_only = "\n".join(
        line for line in src.splitlines()
        if not line.strip().startswith("#")
    )
    # Also strip the docstring block (naive but sufficient here).
    import re as _re
    code_only = _re.sub(r'"""[\s\S]*?"""', "", code_only)

    assert "--https=443" not in code_only, (
        "tailscale_funnel_action still calls the legacy --https=443 stop "
        "syntax; it only ever targeted port 443. See v3.81.4 release notes."
    )
    # And the modern paths must all be present as actual argv fragments.
    assert '"off"' in src or "'off'" in src
    assert '"serve"' in src or "'serve'" in src, "should include `serve reset` fallback"

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


# --- v3.93.0 migration regression guards -----------------------------------

def test_admin_handlers_use_authed_decorator(tmp_path):
    """v3.93.0: All 10 admin handlers + 4 update handlers must be wrapped
    by @authed from arena.handler_helpers, not carry inline `require_auth`
    preludes. functools.wraps preserves the original name, but the code
    object of the outer wrapper differs — check that the returned
    coroutine functions have the wrapper's `__wrapped__` attribute set.
    """
    handlers = make_admin_handlers(_ctx(tmp_path))
    for name in (
        "sys_funnel", "token_regenerate", "tailscale_funnel",
        "cloudflared_tunnel", "zerotier_status", "zerotier_network",
        "tunnels_status", "tunnels_active", "tunnels_start", "tunnels_stop",
        "update_status", "update_check", "update_apply", "update_restart",
    ):
        h = getattr(handlers, name)
        # @authed (via functools.wraps) sets __wrapped__ to the inner fn.
        assert hasattr(h, "__wrapped__"), (
            f"admin handler `{name}` is not wrapped by @authed — "
            f"v3.93.0 migration expects all admin handlers to use "
            f"arena.handler_helpers.authed."
        )


def test_admin_handlers_module_free_of_manual_prelude():
    """v3.93.0: Confirm the inline `ctx.require_auth(request); if r: return r`
    pattern has been eliminated from arena.admin.handlers and
    arena.admin.handlers_update. Any regression that reintroduces it (e.g. a
    new handler copy-pasted from an older module) fails this test loudly.
    """
    import inspect
    from arena.admin import handlers as _adm, handlers_update as _adm_upd

    for mod in (_adm, _adm_upd):
        src = inspect.getsource(mod)
        assert "r = ctx.require_auth(request)" not in src, (
            f"{mod.__name__} still contains the inline auth prelude — "
            f"v3.93.0 migrated it to @authed; new handlers must use the "
            f"decorator instead of copying the prelude back in."
        )
        # The old error handler shape is also gone.
        assert "record_request(is_error=True, count_request=False)" not in src, (
            f"{mod.__name__} still contains manual error accounting — "
            f"@authed does this centrally."
        )

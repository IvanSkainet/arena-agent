"""TLS handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import TlsHandlerContext  # noqa: E402
from arena.tls.handlers import TLS_CONFIG, get_tailscale_cert, make_tls_handlers  # noqa: E402


def test_tls_config_reexported_for_compatibility():
    assert ub._tls_config is TLS_CONFIG
    assert "enabled" in TLS_CONFIG


def test_tls_tailscale_lookup_returns_pair():
    cert, key = get_tailscale_cert()
    assert isinstance(cert, str)
    assert isinstance(key, str)


def test_tls_handlers_factory_outputs():
    ctx = TlsHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        generate_self_signed_cert=ub._generate_self_signed_cert,
        get_tailscale_cert=ub._get_tailscale_cert,
        log_info=ub.log.info,
    )
    handlers = make_tls_handlers(ctx)
    assert callable(handlers.tls)


def test_tls_routes_registered():
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
    assert ("GET", "/v1/tls") in paths
    assert ("POST", "/v1/tls") in paths

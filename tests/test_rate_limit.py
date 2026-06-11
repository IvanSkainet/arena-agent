"""Rate limit helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.rate_limit as rl  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_rate_limit_config_update_and_stats():
    old = dict(rl._rl_v2_config)
    try:
        rl.update_rate_limit_config({"enabled": False, "default_limit": 123, "window_seconds": 7})
        assert rl._rl_v2_config["enabled"] is False
        assert rl._rl_v2_config["default_limit"] == 123
        assert rl._rl_v2_config["window_seconds"] == 7
        stats = rl.rate_limit_stats()
        assert stats["ok"] is True
        assert "active_users" in stats["stats"]
    finally:
        rl._rl_v2_config.clear(); rl._rl_v2_config.update(old)


def test_unified_bridge_rate_limit_reexports():
    assert ub._rl_v2_config is rl._rl_v2_config
    assert callable(ub._check_rate_limit_v2)
    assert callable(ub._check_rate_limit)


def test_ratelimit_route_registered():
    app = ub.make_app({"token": "test", "profile": "owner-shell", "root": "/tmp", "active_exec": 0, "max_concurrent": 3, "audit": "audit"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/ratelimit") in paths
    assert ("POST", "/v1/ratelimit") in paths

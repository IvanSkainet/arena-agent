"""Rate limit helper tests."""
import threading
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


class _TrackingLock:
    def __init__(self):
        self._lock = threading.Lock()
        self.held = False

    def __enter__(self):
        self._lock.acquire()
        self.held = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.held = False
        self._lock.release()


class _LockedDict(dict):
    def __init__(self, lock, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock_ref = lock

    def _assert_locked(self):
        assert self._lock_ref.held is True, "shared rate-limit store accessed outside lock"

    def __contains__(self, key):
        self._assert_locked()
        return super().__contains__(key)

    def __getitem__(self, key):
        self._assert_locked()
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        self._assert_locked()
        return super().__setitem__(key, value)

    def __delitem__(self, key):
        self._assert_locked()
        return super().__delitem__(key)


def test_rate_limit_v2_store_cleanup_happens_under_lock(monkeypatch):
    old_store = rl._rl_v2_store
    old_lock = rl._rl_v2_lock
    old_cfg = dict(rl._rl_v2_config)
    lock = _TrackingLock()
    store = _LockedDict(lock)

    class _Req(dict):
        remote = "127.0.0.1"
        path = "/v1/test"

    try:
        monkeypatch.setattr(rl, "_rl_v2_lock", lock)
        monkeypatch.setattr(rl, "_rl_v2_store", store)
        rl._rl_v2_config.clear()
        rl._rl_v2_config.update({
            "enabled": True,
            "default_limit": 5,
            "per_user_limits": {},
            "per_endpoint_limits": {},
            "window_seconds": 60,
        })
        req = _Req()
        resp = rl.check_rate_limit_v2(
            req,
            check_auth_with_role_fn=lambda request: (False, ""),
            cors_json_response_fn=ub._cors_json_response,
        )
        assert resp is None
        assert req["_rl_headers"]["X-RateLimit-Limit"] == "5"
    finally:
        monkeypatch.setattr(rl, "_rl_v2_store", old_store)
        monkeypatch.setattr(rl, "_rl_v2_lock", old_lock)
        rl._rl_v2_config.clear()
        rl._rl_v2_config.update(old_cfg)

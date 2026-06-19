"""Authentication runtime extraction tests."""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.app_keys import APP_CFG  # noqa: E402
from arena.auth.runtime import AuthRuntimeContext, make_auth_runtime  # noqa: E402


class _Request:
    def __init__(self, token="", header="Authorization", remote="127.0.0.1"):
        self.headers = {}
        if token:
            if header == "Authorization":
                self.headers["Authorization"] = f"Bearer {token}"
            else:
                self.headers["X-Arena-Token"] = token
        self.remote = remote
        self.app = {APP_CFG: {"token": "primary"}}


class _UserStore:
    def __init__(self):
        self.users = {"user-token": {"role": "user", "name": "u"}}

    def load_users(self):
        return self.users

    def check_auth_with_role(self, request, required_role=None):
        token = ""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        elif request.headers.get("X-Arena-Token"):
            token = request.headers["X-Arena-Token"]
        if token == "user-token":
            return True, "user"
        if token == request.app[APP_CFG]["token"]:
            return True, "admin"
        return False, ""


def _runtime(store=None, now=lambda: 1.0, rate_store=None):
    return make_auth_runtime(AuthRuntimeContext(
        user_store=store or _UserStore(),
        rate_limit_lock=threading.Lock(),
        rate_limit_store=rate_store if rate_store is not None else {},
        cors_json_response=ub._cors_json_response,
        log_warning=lambda *args, **kwargs: None,
        now=now,
    ))


def _json(response):
    return ub.json.loads(response.text)


def test_unified_auth_runtime_bindings():
    assert ub.check_auth.__module__ == "arena.auth.runtime"
    assert ub.require_auth.__module__ == "arena.auth.runtime"
    assert ub.check_auth_with_role.__module__ == "arena.auth.runtime"
    assert ub._load_users.__module__ == "arena.auth.runtime"


def test_check_auth_primary_and_x_arena_token_and_user_token():
    runtime = _runtime()
    assert runtime.check_auth(_Request("primary")) is True
    assert runtime.check_auth(_Request("primary", header="X-Arena-Token")) is True
    assert runtime.check_auth(_Request("user-token")) is True
    assert runtime.check_auth(_Request("bad")) is False


def test_require_auth_unauthorized_and_rate_limited():
    rate_store = {}
    runtime = _runtime(now=lambda: 10.0, rate_store=rate_store)
    response = runtime.require_auth(_Request("bad"))
    assert response.status == 401
    assert _json(response) == {"ok": False, "error": "unauthorized"}

    rate_store["auth_fail:127.0.0.1"] = [9.0] * 10
    response = runtime.require_auth(_Request("bad"))
    assert response.status == 429
    assert response.headers.get("Retry-After") == "60"
    assert _json(response)["error"] == "too many failed auth attempts, try again later"


def test_require_auth_success_returns_none():
    assert _runtime().require_auth(_Request("primary")) is None

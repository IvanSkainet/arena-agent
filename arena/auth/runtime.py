"""Authentication runtime helpers and compatibility wrappers."""
from __future__ import annotations

import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from arena.auth.users import UserStore


@dataclass(frozen=True)
class AuthRuntimeContext:
    user_store: UserStore
    rate_limit_lock: Any
    rate_limit_store: dict[str, list[float]]
    cors_json_response: Callable[..., web.Response]
    log_warning: Callable[..., None]
    now: Callable[[], float] = time.time


@dataclass(frozen=True)
class AuthRuntime:
    load_users: Callable[[], dict[str, dict]]
    check_auth_with_role: Callable[[web.Request, str | None], tuple[bool, str]]
    check_auth: Callable[[web.Request], bool]
    require_auth: Callable[[web.Request], web.Response | None]


def make_auth_runtime(ctx: AuthRuntimeContext) -> AuthRuntime:
    def _load_users() -> dict[str, dict]:
        return ctx.user_store.load_users()

    def check_auth_with_role(request: web.Request, required_role: str | None = None) -> tuple[bool, str]:
        return ctx.user_store.check_auth_with_role(request, required_role=required_role)

    def check_auth(request: web.Request) -> bool:
        cfg = request.app["cfg"]
        token = cfg["token"]
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], token):
            return True
        xt = request.headers.get("X-Arena-Token", "")
        if xt and hmac.compare_digest(xt, token):
            return True
        is_authed, _ = check_auth_with_role(request)
        if is_authed:
            return True
        return False

    def require_auth(request: web.Request) -> web.Response | None:
        """Returns None if auth OK, or a 401/429 Response if not."""
        if check_auth(request):
            return None
        peer = request.remote or "unknown"
        now = ctx.now()
        with ctx.rate_limit_lock:
            key = f"auth_fail:{peer}"
            if key not in ctx.rate_limit_store:
                ctx.rate_limit_store[key] = []
            ctx.rate_limit_store[key] = [t for t in ctx.rate_limit_store[key] if now - t < 60]
            if len(ctx.rate_limit_store[key]) >= 10:
                ctx.log_warning("[Auth-RateLimit] IP %s has %d failed auth attempts in 60s", peer, len(ctx.rate_limit_store[key]))
                return ctx.cors_json_response(
                    {"ok": False, "error": "too many failed auth attempts, try again later"},
                    status=429,
                    extra_headers={"Retry-After": "60"},
                )
            ctx.rate_limit_store[key].append(now)
        return ctx.cors_json_response({"ok": False, "error": "unauthorized"}, status=401)

    return AuthRuntime(
        load_users=_load_users,
        check_auth_with_role=check_auth_with_role,
        check_auth=check_auth,
        require_auth=require_auth,
    )

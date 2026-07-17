"""Authentication runtime helpers and compatibility wrappers."""
from __future__ import annotations

import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web
from arena.app_keys import APP_CFG

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

    def _presented_tokens(request: web.Request) -> list[str]:
        """Every token the caller might have presented, in preference
        order. Order matters because we short-circuit on the first
        constant-time match.

        v4.41.0: query-string tokens (``?token=...``) are still
        accepted for backward compatibility with WebSocket
        clients that cannot set an Authorization header from
        the browser (see ``dashboard/assets/41-live-charts.js``),
        but we now flag the request with
        ``request["auth_via_query_token"] = True`` so the
        error middleware can attach a ``Warning: 299`` response
        header and the request-level audit log records that
        the token entered via a deprecated channel. That gives
        operators a way to notice their own leaky scripts before
        we remove the code path entirely in a future release.
        Header-based tokens do not set the flag — they are the
        canonical path and stay silent.
        """
        out: list[str] = []
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            out.append(auth[7:])
        xt = request.headers.get("X-Arena-Token", "")
        if xt:
            out.append(xt)
        query = getattr(request, "query", None)
        if query:
            try:
                qt = query.get("token", "")
            except AttributeError:
                qt = ""
            if qt:
                out.append(qt)
                # Mark the request so the error middleware can
                # attach a deprecation Warning header. Skip when
                # a header-based token was also presented -- in
                # that case the query token was redundant, and
                # attaching a warning would be noisy.
                if not auth.startswith("Bearer ") and not xt:
                    try:
                        request["auth_via_query_token"] = True
                    except (AttributeError, TypeError):
                        # Test doubles that don't support
                        # subscript assignment silently skip
                        # the annotation.
                        pass
        return out

    def check_auth(request: web.Request) -> bool:
        cfg = request.app[APP_CFG]
        master = cfg["token"]
        candidates = _presented_tokens(request)
        for cand in candidates:
            if hmac.compare_digest(cand, master):
                return True
        # v3.86.0: multi-agent bearer tokens. Recognise `agent-<id>-<hex>`
        # by consulting the process-wide registry. On a hit we attach
        # the agent record onto the request so downstream handlers +
        # audit can scope by agent without re-parsing the token.
        try:
            from arena.multiagent import agents as _agents
            for cand in candidates:
                if _agents.looks_like_agent_token(cand):
                    rec = _agents.resolve_token(cand)
                    if rec is not None:
                        try:
                            request["agent_id"] = rec.agent_id
                            request["agent_label"] = rec.label
                        except (AttributeError, TypeError):
                            pass
                        _agents.note_request(rec.agent_id)
                        return True
        except ImportError:
            pass
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

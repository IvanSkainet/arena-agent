"""Rate limiting state, checks, config and stats."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from aiohttp import web

# per-IP rate limiter.
_rate_limit_window: float = 60.0
_rate_limit_max: int = 300
_rate_limit_store: dict[str, list[float]] = {}
_rate_limit_lock = threading.Lock()

# Enhanced v2 limiter.
_rl_v2_config: dict[str, Any] = {
    "enabled": True,
    "default_limit": 300,
    "per_user_limits": {},
    "per_endpoint_limits": {},
    "window_seconds": 60,
}
_rl_v2_store: dict[str, dict[str, list[float]]] = {}
_rl_v2_lock = threading.Lock()


def check_rate_limit_v2(
    request: web.Request,
    *,
    check_auth_with_role_fn: Callable[[web.Request], tuple[bool, str]],
    cors_json_response_fn: Callable[..., web.Response],
) -> web.Response | None:
    if not _rl_v2_config["enabled"]:
        return None
    is_auth, role = check_auth_with_role_fn(request)
    peer = request.remote or "anonymous"
    user_id = f"{peer}:{role}" if is_auth else f"{peer}:anonymous"
    path = request.path
    limit = _rl_v2_config["default_limit"]
    if is_auth and role in _rl_v2_config["per_user_limits"]:
        limit = _rl_v2_config["per_user_limits"][role]
    for prefix, ep_limit in sorted(_rl_v2_config["per_endpoint_limits"].items(), key=lambda item: -len(item[0])):
        if path.startswith(prefix):
            limit = min(limit, ep_limit)
            break
    window = _rl_v2_config["window_seconds"]
    now = time.time()
    with _rl_v2_lock:
        if user_id not in _rl_v2_store:
            _rl_v2_store[user_id] = {}
        ep_store = _rl_v2_store[user_id].setdefault(path, [])
        ep_store[:] = [t for t in ep_store if now - t < window]
        remaining = limit - len(ep_store)
        reset_at = now + window if ep_store else now + window
        if remaining <= 0:
            ep_store.append(now)
            retry_after = round(window - (now - ep_store[0]), 1)
            resp = cors_json_response_fn(
                {"ok": False, "error": "rate limit exceeded", "retry_after_s": retry_after, "limit": limit, "window_s": window},
                status=429,
            )
            resp.headers["X-RateLimit-Limit"] = str(limit)
            resp.headers["X-RateLimit-Remaining"] = "0"
            resp.headers["X-RateLimit-Reset"] = str(int(reset_at))
            resp.headers["Retry-After"] = str(retry_after)
            return resp
        ep_store.append(now)
        _rl_v2_store[user_id] = {key: value for key, value in _rl_v2_store[user_id].items() if value}
        if not _rl_v2_store[user_id]:
            del _rl_v2_store[user_id]
    request["_rl_headers"] = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining - 1),
        "X-RateLimit-Reset": str(int(reset_at)),
    }
    return None


def update_rate_limit_config(data: dict[str, Any]) -> None:
    if "enabled" in data:
        _rl_v2_config["enabled"] = bool(data["enabled"])
    if "default_limit" in data:
        _rl_v2_config["default_limit"] = int(data["default_limit"])
    if "per_user_limits" in data:
        _rl_v2_config["per_user_limits"] = data["per_user_limits"]
    if "per_endpoint_limits" in data:
        _rl_v2_config["per_endpoint_limits"] = data["per_endpoint_limits"]
    if "window_seconds" in data:
        _rl_v2_config["window_seconds"] = max(5, int(data["window_seconds"]))


def rate_limit_stats() -> dict[str, Any]:
    active_users = 0
    total_tracked = 0
    with _rl_v2_lock:
        for _user_id, endpoints in _rl_v2_store.items():
            for _ep, timestamps in endpoints.items():
                total_tracked += len(timestamps)
            active_users += 1
    return {"ok": True, "config": _rl_v2_config, "stats": {"active_users": active_users, "total_tracked_requests": total_tracked}}


def check_rate_limit(
    request: web.Request,
    *,
    cors_json_response_fn: Callable[..., web.Response],
) -> web.Response | None:
    peer = request.remote or "anonymous"
    now = time.time()
    with _rate_limit_lock:
        timestamps = _rate_limit_store.get(peer, [])
        timestamps = [t for t in timestamps if now - t < _rate_limit_window]
        if not timestamps and peer in _rate_limit_store:
            del _rate_limit_store[peer]
            return None
        if len(timestamps) >= _rate_limit_max:
            _rate_limit_store[peer] = timestamps
            return cors_json_response_fn(
                {"ok": False, "error": "rate limit exceeded", "retry_after_s": round(_rate_limit_window - (now - timestamps[0]), 1)},
                status=429,
            )
        timestamps.append(now)
        _rate_limit_store[peer] = timestamps
    return None

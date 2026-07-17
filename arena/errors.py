"""Structured bridge exceptions and global aiohttp error middleware."""
from __future__ import annotations

import asyncio
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web


class BridgeError(Exception):
    """Base exception for all bridge errors. Carries an error_code and HTTP status."""
    error_code: str = "BRIDGE_ERROR"
    http_status: int = 500

    def __init__(self, message: str = "", error_code: str = "", http_status: int = 0):
        super().__init__(message)
        if error_code:
            self.error_code = error_code
        if http_status:
            self.http_status = http_status

    def to_dict(self) -> dict:
        return {"ok": False, "error": str(self), "error_code": self.error_code}


class ValidationError(BridgeError):
    """Input validation failure (400)."""
    error_code = "VALIDATION_ERROR"
    http_status = 400


class AuthError(BridgeError):
    """Authentication failure (401)."""
    error_code = "AUTH_ERROR"
    http_status = 401


class ForbiddenError(BridgeError):
    """Action not allowed (403)."""
    error_code = "FORBIDDEN"
    http_status = 403


class NotFoundError(BridgeError):
    """Resource not found (404)."""
    error_code = "NOT_FOUND"
    http_status = 404


class BridgeTimeoutError(BridgeError):
    """Operation timed out (408)."""
    error_code = "TIMEOUT"
    http_status = 408


class ResourceError(BridgeError):
    """Resource limit exceeded or unavailable (429/503)."""
    error_code = "RESOURCE_ERROR"
    http_status = 503


@dataclass(frozen=True)
class ErrorMiddlewareContext:
    check_rate_limit_v2: Callable[[web.Request], web.Response | None]
    check_rate_limit: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    log_request_response: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    audit: Callable[[dict[str, Any]], None]
    log_debug: Callable[..., None]
    log_warning: Callable[..., None]
    log_error: Callable[..., None]


def make_error_middleware(ctx: ErrorMiddlewareContext):
    @web.middleware
    async def error_middleware(request: web.Request, handler):
        """Catch unhandled exceptions, return structured JSON, log stack traces."""
        if request.path not in ("/health", "/metrics", "/gui", "/", "/favicon.ico", "/api-docs"):
            rl = ctx.check_rate_limit_v2(request) or ctx.check_rate_limit(request)
            if rl:
                return rl

        req_id = (request.headers.get("X-Request-Id") or str(uuid.uuid4())[:8])[:64]
        request["req_id"] = req_id

        t0 = time.time()
        try:
            resp = await handler(request)
            duration = time.time() - t0
            ctx.log_debug("[%s] %s %s -> %d (%.3fs)", req_id, request.method, request.path, resp.status, duration)
            ctx.log_request_response(request.method, request.path, resp.status, duration, req_id, request.remote or "")
            resp.headers["X-Request-Id"] = req_id
            # v4.41.0: query-string tokens are deprecated. When
            # the auth layer flagged this request as
            # ``auth_via_query_token``, attach an RFC-7234
            # ``Warning: 299`` response header so scripts and
            # linters can spot the deprecation without changing
            # exit codes. Also emits a rate-limited server-side
            # log so an operator watching audit sees which peers
            # still use the deprecated channel. The warning is
            # non-blocking -- the request itself succeeds.
            if request.get("auth_via_query_token"):
                resp.headers["Warning"] = (
                    "299 - \"?token= query auth is deprecated; use "
                    "Authorization: Bearer or X-Arena-Token header. "
                    "Query tokens leak into proxy logs, browser "
                    "history, and Referer headers.\""
                )
            return resp
        except web.HTTPException as exc:
            duration = time.time() - t0
            ctx.log_debug("[%s] %s %s -> HTTPException %d (%.3fs)", req_id, request.method, request.path, exc.status, duration)
            ctx.log_request_response(request.method, request.path, exc.status, duration, req_id, request.remote or "")
            exc.headers["Access-Control-Allow-Origin"] = "*"
            exc.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
            exc.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Arena-Token, Mcp-Session-Id"
            exc.headers["X-Request-Id"] = req_id
            # v4.41.0: propagate the same deprecation warning
            # even on HTTPException paths -- otherwise a 302
            # redirect with a legit query token would silently
            # skip the warning.
            if request.get("auth_via_query_token"):
                exc.headers["Warning"] = (
                    "299 - \"?token= query auth is deprecated; use "
                    "Authorization: Bearer or X-Arena-Token header.\""
                )
            raise
        except BridgeError as e:
            duration = time.time() - t0
            ctx.record_request(duration=duration, is_error=True)
            ctx.log_request_response(request.method, request.path, e.http_status, duration, req_id, request.remote or "", error=str(e))
            ctx.log_warning("[%s] %s %s -> %s %s: %s (%.3fs)", req_id, request.method, request.path, e.error_code, e.http_status, e, duration)
            return ctx.cors_json_response(e.to_dict(), status=e.http_status, extra_headers={"X-Request-Id": req_id})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            duration = time.time() - t0
            ctx.record_request(duration=duration, is_error=True)
            ctx.log_request_response(request.method, request.path, 500, duration, req_id, request.remote or "", error=str(e))
            tb = traceback.format_exc()
            ctx.log_error("[%s] %s %s UNHANDLED: %s\n%s", req_id, request.method, request.path, e, tb)
            try:
                ctx.audit({
                    "event": "unhandled_error",
                    "req_id": req_id,
                    "path": request.path,
                    "method": request.method,
                    "error": repr(e),
                    "tb_snippet": tb[:2000],
                })
            except Exception:
                pass
            return ctx.cors_json_response({
                "ok": False,
                "error": "Internal server error",
                "error_code": "INTERNAL_ERROR",
                "req_id": req_id,
            }, status=500, extra_headers={"X-Request-Id": req_id})

    return error_middleware

"""Tests for the v4.41.0 ``?token=`` query-string auth
deprecation (audit finding #3).

Behaviour under test:

* A query-only token still authenticates (backward compat for
  WebSocket clients that cannot set Authorization from the
  browser).
* When the token entered via query, ``request["auth_via_query_token"]``
  is set to True.
* Header-based tokens (Authorization / X-Arena-Token) do NOT
  set the flag -- they are the canonical path.
* When both a header AND a query token are presented, the flag
  is NOT set (the query token was redundant, warning would be
  noisy).
* Test doubles that don't support subscript assignment don't
  crash the auth path.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.app_keys import APP_CFG  # noqa: E402
from arena.auth.runtime import AuthRuntimeContext, make_auth_runtime  # noqa: E402


class _Request:
    """Test double mimicking aiohttp.web.Request just enough
    for the auth path. Supports both header and query token
    presentation."""

    def __init__(self, *, bearer=None, x_token=None, query_token=None,
                 remote="127.0.0.1"):
        self.headers = {}
        if bearer:
            self.headers["Authorization"] = f"Bearer {bearer}"
        if x_token:
            self.headers["X-Arena-Token"] = x_token
        self.query = {}
        if query_token:
            self.query["token"] = query_token
        self.remote = remote
        self.app = {APP_CFG: {"token": "primary"}}
        self._items: dict = {}

    def __setitem__(self, k, v):
        self._items[k] = v

    def __getitem__(self, k):
        return self._items[k]

    def get(self, k, default=None):
        return self._items.get(k, default)


class _NoSubscriptRequest(_Request):
    """A request-like object whose ``__setitem__`` raises --
    matches the ``AttributeError`` / ``TypeError`` guard in
    _presented_tokens."""

    def __setitem__(self, k, v):
        raise AttributeError("no assignment support")


class _UserStore:
    def load_users(self):
        return {}

    def check_auth_with_role(self, request, required_role=None):
        return False, ""


def _runtime():
    return make_auth_runtime(AuthRuntimeContext(
        user_store=_UserStore(),
        rate_limit_lock=threading.Lock(),
        rate_limit_store={},
        cors_json_response=ub._cors_json_response,
        log_warning=lambda *a, **kw: None,
        now=lambda: 1.0,
    ))


# ---------------------------------------------------------------------------
# Auth still works via query
# ---------------------------------------------------------------------------
def test_query_only_token_still_authenticates():
    r = _Request(query_token="primary")
    assert _runtime().check_auth(r) is True


def test_header_only_token_still_authenticates():
    r = _Request(bearer="primary")
    assert _runtime().check_auth(r) is True


def test_x_arena_token_still_authenticates():
    r = _Request(x_token="primary")
    assert _runtime().check_auth(r) is True


# ---------------------------------------------------------------------------
# Deprecation flag
# ---------------------------------------------------------------------------
def test_query_only_sets_deprecation_flag():
    """v4.41.0: query-only auth is deprecated. The auth layer
    marks the request so the error middleware can attach a
    Warning header."""
    r = _Request(query_token="primary")
    _runtime().check_auth(r)
    assert r.get("auth_via_query_token") is True


def test_bearer_header_does_not_set_deprecation_flag():
    """Header-based auth is the canonical path and must not be
    flagged. Otherwise every request gets a spurious warning."""
    r = _Request(bearer="primary")
    _runtime().check_auth(r)
    assert r.get("auth_via_query_token") is None


def test_x_arena_header_does_not_set_deprecation_flag():
    r = _Request(x_token="primary")
    _runtime().check_auth(r)
    assert r.get("auth_via_query_token") is None


def test_both_header_and_query_does_not_set_flag():
    """When the caller also sent a header, the query token was
    redundant. Warning would be noise."""
    r = _Request(bearer="primary", query_token="primary")
    _runtime().check_auth(r)
    assert r.get("auth_via_query_token") is None


def test_both_x_arena_and_query_does_not_set_flag():
    r = _Request(x_token="primary", query_token="primary")
    _runtime().check_auth(r)
    assert r.get("auth_via_query_token") is None


def test_query_token_failed_auth_still_leaves_flag():
    """Even when the query token was wrong, we mark the request
    -- otherwise the rate-limit response would silently omit
    the deprecation signal for callers who are getting close to
    the retry limit."""
    r = _Request(query_token="wrong")
    assert _runtime().check_auth(r) is False
    # Presented via query -> flag set even on failure.
    assert r.get("auth_via_query_token") is True


# ---------------------------------------------------------------------------
# Robustness -- test doubles without subscript support
# ---------------------------------------------------------------------------
def test_request_without_subscript_support_does_not_crash():
    """If the request object refuses ``__setitem__`` (some
    lightweight test doubles), auth should still proceed rather
    than blowing up."""
    r = _NoSubscriptRequest(query_token="primary")
    # Must not raise.
    assert _runtime().check_auth(r) is True

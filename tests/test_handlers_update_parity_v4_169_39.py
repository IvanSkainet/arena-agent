"""v4.169.39 -- arena.admin.handlers_update parity tests (mutation-driven).

Fast, deterministic in-memory tests targeting 100% mutation kill rate for
`arena/admin/handlers_update.py`:
* `make_update_handlers` keys and callable registrations;
* Auth enforcement verification on all 6 handlers;
* `handle_update_status` on Linux, macOS, Windows, FreeBSD, token exceptions, smoke exceptions;
* `handle_update_check` with/without custom repo override, whitespace stripping, json decode fallback, audit payload;
* `handle_update_apply`:
    - JSON parsing error handling (400 "JSON body required");
    - Required field validation (tag, asset_url, asset_name) -> 400;
    - SHA256 / accept_no_verification validation -> 400;
    - Consent challenge response shape, sha256 prefix splitting ("sha256:abc" vs "abc"), "UNVERIFIED" digest;
    - Verified vs unverified execution;
    - Audit logging for apply, restart_scheduled, and restart_refused;
    - Smoke test pending marker handling (success & exception branches);
    - `restart_process` result extraction, fallback to "scheduled", ok=False -> restart_refused;
* `handle_update_restart` with default force=False, force=True, non-dict json fallback, audit payload;
* `handle_update_token_set` and `handle_update_token_clear` execution, argument passing, audit payload.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.admin.handlers_update import make_update_handlers  # noqa: E402
from arena.constants import VERSION  # noqa: E402


class _MockContext:
    def __init__(self, reject_auth: bool = False) -> None:
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.reject_auth = reject_auth
        self.auth_calls: list[Any] = []
        self.audit_events: list[dict[str, Any]] = []

    def require_auth(self, request: Any) -> Any:
        self.auth_calls.append(request)
        if self.reject_auth or request.headers.get("Authorization") != "Bearer t":
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        return None

    def record_request(self, *args: Any, **kwargs: Any) -> None:
        pass

    def cors_json_response(self, data: Any, status: int = 200) -> web.Response:
        return web.json_response(data, status=status)

    def audit(self, event: dict[str, Any]) -> None:
        self.audit_events.append(dict(event))


def _make_req(
    method: str,
    path: str,
    payload: Any = None,
    is_bad_json: bool = False,
    auth_header: str = "Bearer t",
) -> web.Request:
    headers = {"Authorization": auth_header} if auth_header else {}
    req = make_mocked_request(method, path, headers=headers)
    if is_bad_json:
        async def _bad():
            raise json.JSONDecodeError("Expecting value", "doc", 0)
        req.json = _bad
    else:
        async def _good():
            return payload if payload is not None else {}
        req.json = _good
    return req


# ---------------------------------------------------------------------------
# Handler Registration & Auth Enforcement
# ---------------------------------------------------------------------------

def test_make_update_handlers_keys():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    expected_keys = {
        "update_status",
        "update_check",
        "update_apply",
        "update_restart",
        "update_token_set",
        "update_token_clear",
    }
    assert set(handlers.keys()) == expected_keys
    assert handlers["update_status"].__name__ == "handle_update_status"
    assert handlers["update_check"].__name__ == "handle_update_check"
    assert handlers["update_apply"].__name__ == "handle_update_apply"
    assert handlers["update_restart"].__name__ == "handle_update_restart"
    assert handlers["update_token_set"].__name__ == "handle_update_token_set"
    assert handlers["update_token_clear"].__name__ == "handle_update_token_clear"
    for k in expected_keys:
        assert callable(handlers[k])


@pytest.mark.parametrize("handler_key,method,path", [
    ("update_status", "GET", "/v1/admin/update/status"),
    ("update_check", "POST", "/v1/admin/update/check"),
    ("update_apply", "POST", "/v1/admin/update/apply"),
    ("update_restart", "POST", "/v1/admin/update/restart"),
    ("update_token_set", "POST", "/v1/admin/update/token-set"),
    ("update_token_clear", "POST", "/v1/admin/update/token-clear"),
])
def test_all_handlers_require_auth(handler_key, method, path):
    ctx = _MockContext(reject_auth=True)
    handlers = make_update_handlers(ctx)
    req = _make_req(method, path, auth_header="")
    resp = asyncio.run(handlers[handler_key](req))
    assert resp.status == 401
    assert len(ctx.auth_calls) == 1


# ---------------------------------------------------------------------------
# handle_update_status
# ---------------------------------------------------------------------------

def test_update_status_linux():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    req = _make_req("GET", "/v1/admin/update/status")
    fake_root = Path("/opt/arena")

    with patch("platform.system", return_value="Linux"), \
         patch("arena.admin.auto_update._repo", return_value="IvanSkainet/arena-agent"), \
         patch("arena.admin.auto_update._install_root", return_value=fake_root), \
         patch("arena.admin.update_github.github_token_source", return_value="env"), \
         patch("arena.ship.post_update_smoke.status", return_value={"ok": True, "pending": False}):
        resp = asyncio.run(handlers["update_status"](req))
        assert resp.status == 200
        body = json.loads(resp.text)
        assert body["ok"] is True
        assert body["current"] == VERSION
        assert body["repo"] == "IvanSkainet/arena-agent"
        assert body["install_root"] == str(fake_root)
        assert body["platform"] == "linux"
        assert body["platform_display"] == "GNU/Linux"
        assert body["restart_hint"] == "systemd / launchd will restart automatically on exit."
        assert body["github_token_source"] == "env"
        assert body["post_update_smoke"] == {"ok": True, "pending": False}


def test_update_status_darwin():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    req = _make_req("GET", "/v1/admin/update/status")

    with patch("platform.system", return_value="Darwin"), \
         patch("arena.admin.auto_update._repo", return_value="repo/test"), \
         patch("arena.admin.auto_update._install_root", return_value=Path("/tmp")), \
         patch("arena.admin.update_github.github_token_source", return_value="file"), \
         patch("arena.ship.post_update_smoke.status", return_value={"ok": True}):
        resp = asyncio.run(handlers["update_status"](req))
        assert resp.status == 200
        body = json.loads(resp.text)
        assert body["platform"] == "darwin"
        assert body["platform_display"] == "macOS"
        assert body["restart_hint"] == "systemd / launchd will restart automatically on exit."


def test_update_status_windows():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    req = _make_req("GET", "/v1/admin/update/status")

    with patch("platform.system", return_value="Windows"), \
         patch("arena.admin.auto_update._repo", return_value="repo/win"), \
         patch("arena.admin.auto_update._install_root", return_value=Path("C:/arena")), \
         patch("arena.admin.update_github.github_token_source", return_value="none"), \
         patch("arena.ship.post_update_smoke.status", return_value={"ok": True}):
        resp = asyncio.run(handlers["update_status"](req))
        assert resp.status == 200
        body = json.loads(resp.text)
        assert body["platform"] == "windows"
        assert body["platform_display"] == "Windows"
        assert body["restart_hint"] == "Windows: service supervisor (nssm / Windows service) will relaunch after apply."


def test_update_status_other_os_and_exceptions():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    req = _make_req("GET", "/v1/admin/update/status")

    with patch("platform.system", return_value="FreeBSD"), \
         patch("arena.admin.auto_update._repo", return_value="repo/bsd"), \
         patch("arena.admin.auto_update._install_root", return_value=Path("/usr/local")), \
         patch("arena.admin.update_github.github_token_source", side_effect=RuntimeError("no token module")), \
         patch("arena.ship.post_update_smoke.status", side_effect=ValueError("smoke failed")):
        resp = asyncio.run(handlers["update_status"](req))
        assert resp.status == 200
        body = json.loads(resp.text)
        assert body["platform"] == "freebsd"
        assert body["platform_display"] == "Freebsd"
        assert body["github_token_source"] == "unknown"
        assert body["post_update_smoke"] == {"ok": False, "error": "smoke failed"}


# ---------------------------------------------------------------------------
# handle_update_check
# ---------------------------------------------------------------------------

def test_update_check_default():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    req = _make_req("POST", "/v1/admin/update/check", {})

    check_res = {
        "ok": True,
        "current": "4.169.38",
        "latest": "4.169.39",
        "needs_update": True,
    }
    with patch("arena.admin.auto_update.check_updates", return_value=check_res):
        resp = asyncio.run(handlers["update_check"](req))
        assert resp.status == 200
        body = json.loads(resp.text)
        assert body == check_res
        assert len(ctx.audit_events) == 1
        assert ctx.audit_events[0] == {
            "type": "admin.update.check",
            "current": "4.169.38",
            "latest": "4.169.39",
            "needs_update": True,
            "ok": True,
        }


def test_update_check_with_repo_override_and_malformed_json(monkeypatch):
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)

    monkeypatch.delenv("ARENA_UPDATE_REPO", raising=False)
    req = _make_req("POST", "/v1/admin/update/check", {"repo": "custom/repo-test "})

    check_res = {"ok": True, "current": "1.0", "latest": "1.0", "needs_update": False}
    with patch("arena.admin.auto_update.check_updates", return_value=check_res):
        resp = asyncio.run(handlers["update_check"](req))
        assert resp.status == 200
        import os
        assert os.environ.get("ARENA_UPDATE_REPO") == "custom/repo-test"

    # Malformed json fallback
    req_bad = _make_req("POST", "/v1/admin/update/check", is_bad_json=True)
    with patch("arena.admin.auto_update.check_updates", return_value=check_res):
        resp_bad = asyncio.run(handlers["update_check"](req_bad))
        assert resp_bad.status == 200


# ---------------------------------------------------------------------------
# handle_update_apply
# ---------------------------------------------------------------------------

def test_update_apply_bad_json():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    req = _make_req("POST", "/v1/admin/update/apply", is_bad_json=True)

    resp = asyncio.run(handlers["update_apply"](req))
    assert resp.status == 400
    body = json.loads(resp.text)
    assert body["ok"] is False
    assert body["error"] == "JSON body required"


@pytest.mark.parametrize("payload", [
    {"asset_url": "http://x", "asset_name": "a.zip"},
    {"tag": "v1.0", "asset_name": "a.zip"},
    {"tag": "v1.0", "asset_url": "http://x"},
    {"tag": "", "asset_url": "http://x", "asset_name": "a.zip"},
    {"tag": "v1.0", "asset_url": "  ", "asset_name": "a.zip"},
    {"tag": "v1.0", "asset_url": "http://x", "asset_name": ""},
])
def test_update_apply_missing_required_fields(payload):
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    req = _make_req("POST", "/v1/admin/update/apply", payload)

    resp = asyncio.run(handlers["update_apply"](req))
    assert resp.status == 400
    body = json.loads(resp.text)
    assert body["ok"] is False
    assert body["error"] == "tag, asset_url, asset_name all required"


def test_update_apply_missing_sha256_without_unverified_flag():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    payload = {
        "tag": "v1.0",
        "asset_url": "https://example.com/asset.zip",
        "asset_name": "asset.zip",
        "expected_sha256": "",
        "accept_no_verification": False,
    }
    req = _make_req("POST", "/v1/admin/update/apply", payload)

    resp = asyncio.run(handlers["update_apply"](req))
    assert resp.status == 400
    body = json.loads(resp.text)
    assert body["ok"] is False
    assert body["error"] == "expected_sha256 required (or set accept_no_verification=true)"


def test_update_apply_consent_challenge_verified_with_sha256_prefix():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    payload = {
        "tag": "v4.169.39",
        "asset_url": "https://github.com/IvanSkainet/arena-agent/releases/download/v4.169.39/asset.zip",
        "asset_name": "asset.zip",
        "expected_sha256": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    }
    req = _make_req("POST", "/v1/admin/update/apply", payload)

    with patch("arena.admin.auto_update.consent_token", return_value="tok-verified-123") as mock_consent:
        resp = asyncio.run(handlers["update_apply"](req))
        assert resp.status == 200
        mock_consent.assert_called_once_with(
            tag="v4.169.39",
            sha256="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            asset_url="https://github.com/IvanSkainet/arena-agent/releases/download/v4.169.39/asset.zip",
        )
        body = json.loads(resp.text)
        assert body["ok"] is False
        assert body["consent_required"] is True
        assert body["required_consent"] == "tok-verified-123"
        assert body["tag"] == "v4.169.39"
        assert body["asset_name"] == "asset.zip"
        assert body["sha256"] == payload["expected_sha256"]
        assert body["verification"] == "sha256"
        assert body["hint"] == "Resend the same request with consent=<required_consent>."


def test_update_apply_consent_challenge_verified_multiple_colons():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    payload = {
        "tag": "v4.169.39",
        "asset_url": "https://github.com/IvanSkainet/arena-agent/releases/download/v4.169.39/asset.zip",
        "asset_name": "asset.zip",
        "expected_sha256": "prefix:middle:digest_value_here",
    }
    req = _make_req("POST", "/v1/admin/update/apply", payload)

    with patch("arena.admin.auto_update.consent_token", return_value="tok-multi-123") as mock_consent:
        resp = asyncio.run(handlers["update_apply"](req))
        assert resp.status == 200
        # split(":", 1)[-1] keeps "middle:digest_value_here"
        mock_consent.assert_called_once_with(
            tag="v4.169.39",
            sha256="middle:digest_value_here",
            asset_url="https://github.com/IvanSkainet/arena-agent/releases/download/v4.169.39/asset.zip",
        )


def test_update_apply_consent_challenge_verified_without_prefix():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    payload = {
        "tag": "v4.169.39",
        "asset_url": "https://github.com/IvanSkainet/arena-agent/releases/download/v4.169.39/asset.zip",
        "asset_name": "asset.zip",
        "expected_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    }
    req = _make_req("POST", "/v1/admin/update/apply", payload)

    with patch("arena.admin.auto_update.consent_token", return_value="tok-noprefix-123") as mock_consent:
        resp = asyncio.run(handlers["update_apply"](req))
        assert resp.status == 200
        mock_consent.assert_called_once_with(
            tag="v4.169.39",
            sha256="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            asset_url="https://github.com/IvanSkainet/arena-agent/releases/download/v4.169.39/asset.zip",
        )


def test_update_apply_consent_challenge_unverified():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    payload = {
        "tag": "v4.169.39",
        "asset_url": "https://github.com/IvanSkainet/arena-agent/releases/download/v4.169.39/asset.zip",
        "asset_name": "asset.zip",
        "accept_no_verification": True,
    }
    req = _make_req("POST", "/v1/admin/update/apply", payload)

    with patch("arena.admin.auto_update.consent_token", return_value="tok-unverified-456") as mock_consent:
        resp = asyncio.run(handlers["update_apply"](req))
        assert resp.status == 200
        mock_consent.assert_called_once_with(
            tag="v4.169.39",
            sha256="UNVERIFIED",
            asset_url="https://github.com/IvanSkainet/arena-agent/releases/download/v4.169.39/asset.zip",
        )
        body = json.loads(resp.text)
        assert body["ok"] is False
        assert body["consent_required"] is True
        assert body["required_consent"] == "tok-unverified-456"
        assert body["sha256"] is None
        assert body["verification"] == "unverified"


def test_update_apply_restart_defaults_to_true():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    payload = {
        "tag": "v4.169.39",
        "asset_url": "https://example.com/asset.zip",
        "asset_name": "asset.zip",
        "expected_sha256": "abc123",
        "consent": "valid-token",
        # "restart" key intentionally omitted to test default True
    }
    req = _make_req("POST", "/v1/admin/update/apply", payload)

    apply_result = {
        "ok": True,
        "verification": "sha256",
        "downloaded_sha256": "abc123",
        "swapped": True,
        "applied_version": "4.169.39",
        "platform": "linux",
        "install_root": "/opt/arena",
    }
    restart_result = {"ok": True, "restart": "execv_scheduled"}

    with patch("arena.admin.auto_update.apply_update", return_value=dict(apply_result)) as mock_apply, \
         patch("arena.ship.post_update_smoke.mark_pending", return_value={"pending": True, "tag": "v4.169.39"}), \
         patch("arena.admin.auto_update.restart_process", return_value=restart_result) as mock_restart:

        resp = asyncio.run(handlers["update_apply"](req))
        assert resp.status == 200
        mock_apply.assert_called_once_with(
            asset_url="https://example.com/asset.zip",
            asset_name="asset.zip",
            tag="v4.169.39",
            expected_sha256="abc123",
            consent="valid-token",
            restart=True,
            accept_no_verification=False,
        )
        mock_restart.assert_called_once_with(delay_sec=1.0, install_root="/opt/arena")
        body = json.loads(resp.text)
        assert body["ok"] is True
        assert body["restart"] == "execv_scheduled"


def test_windows_update_reuses_its_existing_mover_instead_of_racing_a_second():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    req = _make_req("POST", "/v1/admin/update/apply", {
        "tag": "v4.169.44",
        "asset_url": "https://example.com/asset.zip",
        "asset_name": "asset.zip",
        "expected_sha256": "abc123",
        "consent": "valid-token",
        "restart": True,
    })
    apply_result = {
        "ok": True,
        "verification": "sha256",
        "downloaded_sha256": "abc123",
        "swapped": True,
        "applied_version": "4.169.44",
        "platform": "windows",
        "install_root": "C:/arena",
    }
    with patch("arena.admin.auto_update.apply_update", return_value=apply_result), \
         patch("arena.ship.post_update_smoke.mark_pending", return_value={"pending": True}), \
         patch("arena.admin.auto_update.restart_process", return_value={
             "ok": True, "restart": "scheduled"
         }) as mock_restart:
        resp = asyncio.run(handlers["update_apply"](req))
    assert resp.status == 200
    mock_restart.assert_called_once_with(
        delay_sec=1.0,
        install_root="C:/arena",
        relauncher_prepared=True,
    )


def test_update_apply_success_with_restart_and_smoke_and_restart_ok():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    payload = {
        "tag": "v4.169.39",
        "asset_url": "https://example.com/asset.zip",
        "asset_name": "asset.zip",
        "expected_sha256": "abc123",
        "consent": "valid-token",
        "restart": True,
    }
    req = _make_req("POST", "/v1/admin/update/apply", payload)

    apply_result = {
        "ok": True,
        "verification": "sha256",
        "downloaded_sha256": "abc123",
        "swapped": True,
        "applied_version": "4.169.39",
        "platform": "linux",
        "install_root": "/opt/arena",
    }
    restart_result = {
        "ok": True,
        "restart": "execv_scheduled",
    }

    with patch("arena.admin.auto_update.apply_update", return_value=dict(apply_result)) as mock_apply, \
         patch("arena.ship.post_update_smoke.mark_pending", return_value={"pending": True, "tag": "v4.169.39"}) as mock_smoke, \
         patch("arena.admin.auto_update.restart_process", return_value=restart_result) as mock_restart:

        resp = asyncio.run(handlers["update_apply"](req))
        assert resp.status == 200
        mock_apply.assert_called_once_with(
            asset_url="https://example.com/asset.zip",
            asset_name="asset.zip",
            tag="v4.169.39",
            expected_sha256="abc123",
            consent="valid-token",
            restart=True,
            accept_no_verification=False,
        )
        mock_smoke.assert_called_once_with({
            "tag": "v4.169.39",
            "applied_version": "4.169.39",
            "downloaded_sha256": "abc123",
            "asset_name": "asset.zip",
            "reason": "admin.update.apply",
        })
        mock_restart.assert_called_once_with(delay_sec=1.0, install_root="/opt/arena")

        body = json.loads(resp.text)
        assert body["ok"] is True
        assert body["post_update_smoke"] == {"pending": True, "tag": "v4.169.39"}
        assert body["restart"] == "execv_scheduled"
        assert "restart_refused" not in body

        assert len(ctx.audit_events) == 2
        assert ctx.audit_events[0] == {
            "type": "admin.update.apply",
            "tag": "v4.169.39",
            "sha256": "abc123",
            "verification": "sha256",
            "downloaded_sha256": "abc123",
            "swapped": True,
            "ok": True,
        }
        assert ctx.audit_events[1] == {
            "type": "admin.update.apply.restart_scheduled",
            "tag": "v4.169.39",
            "platform": "linux",
            "delay_sec": 1.0,
        }


def test_update_apply_smoke_exception_and_restart_refused():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    payload = {
        "tag": "v4.169.39",
        "asset_url": "https://example.com/asset.zip",
        "asset_name": "asset.zip",
        "expected_sha256": "",
        "accept_no_verification": True,
        "consent": "valid-token",
        "restart": True,
    }
    req = _make_req("POST", "/v1/admin/update/apply", payload)

    apply_result = {
        "ok": True,
        "verification": "unverified",
        "downloaded_sha256": "def456",
        "swapped": True,
        "applied_version": "4.169.39",
        "platform": "windows",
        "install_root": "C:/arena",
    }
    restart_result = {
        "ok": False,
        "error": "supervisor not found",
        "restart": "refused",
    }

    with patch("arena.admin.auto_update.apply_update", return_value=dict(apply_result)), \
         patch("arena.ship.post_update_smoke.mark_pending", side_effect=RuntimeError("smoke write error")), \
         patch("arena.admin.auto_update.restart_process", return_value=restart_result):

        resp = asyncio.run(handlers["update_apply"](req))
        assert resp.status == 200
        body = json.loads(resp.text)
        assert body["post_update_smoke"] == {"ok": False, "error": "smoke write error"}
        assert body["restart"] == "refused"
        assert body["restart_refused"] == restart_result

        assert len(ctx.audit_events) == 3
        assert ctx.audit_events[0]["type"] == "admin.update.apply"
        assert ctx.audit_events[0]["sha256"] == "UNVERIFIED"
        assert ctx.audit_events[1]["type"] == "admin.update.apply.restart_scheduled"
        assert ctx.audit_events[2] == {
            "type": "admin.update.apply.restart_refused",
            "tag": "v4.169.39",
            "reason": "supervisor not found",
        }


def test_update_apply_res_not_dict():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    payload = {
        "tag": "v1.0",
        "asset_url": "https://example.com/asset.zip",
        "asset_name": "asset.zip",
        "expected_sha256": "abc123",
        "consent": "valid-token",
        "restart": True,
    }
    req = _make_req("POST", "/v1/admin/update/apply", payload)

    with patch("arena.admin.auto_update.apply_update", return_value="invalid string"):
        resp = asyncio.run(handlers["update_apply"](req))
        assert resp.status == 200
        assert len(ctx.audit_events) == 1
        assert ctx.audit_events[0] == {
            "type": "admin.update.apply",
            "tag": "v1.0",
            "sha256": "abc123",
            "verification": None,
            "downloaded_sha256": None,
            "swapped": None,
            "ok": False,
        }


def test_update_apply_restart_res_missing_restart_key():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    payload = {
        "tag": "v4.169.39",
        "asset_url": "https://example.com/asset.zip",
        "asset_name": "asset.zip",
        "expected_sha256": "abc123",
        "consent": "valid-token",
    }
    req = _make_req("POST", "/v1/admin/update/apply", payload)

    apply_result = {
        "ok": True,
        "verification": "sha256",
        "downloaded_sha256": "abc123",
        "swapped": True,
        "applied_version": "4.169.39",
        "platform": "linux",
        "install_root": "/opt/arena",
    }
    # restart_process returns dict without "ok" or "restart" keys -> should fallback to "scheduled" and ok=True
    restart_result = {"some_other_info": 123}

    with patch("arena.admin.auto_update.apply_update", return_value=dict(apply_result)), \
         patch("arena.ship.post_update_smoke.mark_pending", return_value={"pending": True, "tag": "v4.169.39"}), \
         patch("arena.admin.auto_update.restart_process", return_value=restart_result):

        resp = asyncio.run(handlers["update_apply"](req))
        assert resp.status == 200
        body = json.loads(resp.text)
        assert body["ok"] is True
        assert body["restart"] == "scheduled"
        assert "restart_refused" not in body
        # Should not have restart_refused audit event
        event_types = [e["type"] for e in ctx.audit_events]
        assert "admin.update.apply.restart_refused" not in event_types


def test_update_apply_no_restart_flag_or_failed_apply():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)

    # Failed apply
    req_fail = _make_req("POST", "/v1/admin/update/apply", {
        "tag": "v1", "asset_url": "u", "asset_name": "n", "expected_sha256": "h", "consent": "c"
    })
    with patch("arena.admin.auto_update.apply_update", return_value={"ok": False, "error": "checksum mismatch"}), \
         patch("arena.admin.auto_update.restart_process") as mock_restart:
        resp = asyncio.run(handlers["update_apply"](req_fail))
        body = json.loads(resp.text)
        assert body["ok"] is False
        mock_restart.assert_not_called()
        assert len(ctx.audit_events) == 1
        assert ctx.audit_events[0]["type"] == "admin.update.apply"
        assert ctx.audit_events[0]["ok"] is False

    # Success apply with restart=False
    ctx.audit_events.clear()
    req_norestart = _make_req("POST", "/v1/admin/update/apply", {
        "tag": "v1", "asset_url": "u", "asset_name": "n", "expected_sha256": "h", "consent": "c", "restart": False
    })
    with patch("arena.admin.auto_update.apply_update", return_value={"ok": True, "swapped": True}), \
         patch("arena.admin.auto_update.restart_process") as mock_restart:
        resp = asyncio.run(handlers["update_apply"](req_norestart))
        body = json.loads(resp.text)
        assert body["ok"] is True
        mock_restart.assert_not_called()
        assert len(ctx.audit_events) == 1


# ---------------------------------------------------------------------------
# handle_update_restart
# ---------------------------------------------------------------------------

def test_update_restart_default():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    req = _make_req("POST", "/v1/admin/update/restart", {})

    with patch("arena.admin.auto_update.restart_process", return_value={"ok": True, "restart": "scheduled"}) as mock_r:
        resp = asyncio.run(handlers["update_restart"](req))
        assert resp.status == 200
        mock_r.assert_called_once_with(force=False)
        body = json.loads(resp.text)
        assert body == {"ok": True, "restart": "scheduled"}
        assert len(ctx.audit_events) == 1
        assert ctx.audit_events[0] == {
            "type": "admin.update.restart",
            "ok": True,
            "restart": "scheduled",
        }


def test_update_restart_force_and_bad_json():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    req = _make_req("POST", "/v1/admin/update/restart", {"force": True})

    with patch("arena.admin.auto_update.restart_process", return_value={"ok": True, "restart": "killed"}) as mock_r:
        resp = asyncio.run(handlers["update_restart"](req))
        assert resp.status == 200
        mock_r.assert_called_once_with(force=True)
        body = json.loads(resp.text)
        assert body["restart"] == "killed"

    # Bad json
    req_bad = _make_req("POST", "/v1/admin/update/restart", is_bad_json=True)
    with patch("arena.admin.auto_update.restart_process", return_value={"ok": True}) as mock_r:
        resp_bad = asyncio.run(handlers["update_restart"](req_bad))
        assert resp_bad.status == 200
        mock_r.assert_called_once_with(force=False)


# ---------------------------------------------------------------------------
# handle_update_token_set & handle_update_token_clear
# ---------------------------------------------------------------------------

def test_update_token_set():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    fixture_token = "ghp" + "_" + "secret123"
    req = _make_req("POST", "/v1/admin/update/token-set", {"token": fixture_token})

    with patch("arena.admin.update_github.save_github_token", return_value={"ok": True, "path": "/path"}) as mock_save, \
         patch("arena.admin.update_github.github_token_source", return_value="file"):
        resp = asyncio.run(handlers["update_token_set"](req))
        assert resp.status == 200
        mock_save.assert_called_once_with(fixture_token)
        body = json.loads(resp.text)
        assert body == {"ok": True, "path": "/path"}
        assert len(ctx.audit_events) == 1
        assert ctx.audit_events[0] == {
            "type": "admin.update.token_set",
            "ok": True,
            "source": "file",
        }


def test_update_token_set_bad_json():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    req = _make_req("POST", "/v1/admin/update/token-set", is_bad_json=True)

    with patch("arena.admin.update_github.save_github_token", return_value={"ok": True}) as mock_save, \
         patch("arena.admin.update_github.github_token_source", return_value="none"):
        resp = asyncio.run(handlers["update_token_set"](req))
        assert resp.status == 200
        mock_save.assert_called_once_with("")


def test_update_token_clear():
    ctx = _MockContext()
    handlers = make_update_handlers(ctx)
    req = _make_req("POST", "/v1/admin/update/token-clear", {})

    with patch("arena.admin.update_github.clear_github_token", return_value={"ok": True, "removed": True}) as mock_clear, \
         patch("arena.admin.update_github.github_token_source", return_value="env"):
        resp = asyncio.run(handlers["update_token_clear"](req))
        assert resp.status == 200
        mock_clear.assert_called_once_with()
        body = json.loads(resp.text)
        assert body == {"ok": True, "removed": True}
        assert len(ctx.audit_events) == 1
        assert ctx.audit_events[0] == {
            "type": "admin.update.token_clear",
            "ok": True,
            "removed": True,
            "source": "env",
        }

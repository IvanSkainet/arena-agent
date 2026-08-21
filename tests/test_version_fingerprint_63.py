"""Unauthenticated `/v1/version` must not fingerprint the host (#63).

The endpoint answered anyone who could reach the port with the exact
interpreter patch level and the exact OS build. Captured from the live
bridge before the fix:

    $ curl -s http://127.0.0.1:8765/v1/version     # no token
    {"ok": true, "version": "4.169.48", "service": "arena-unified-bridge",
     "python": "3.14.7", "platform": "Windows-10-10.0.19044-SP0",
     "loopback_only": true, "deployment": {...}}

"Python 3.14.7 on Windows-10-10.0.19044-SP0" is a vulnerability-matching
shortcut: it names the precise CVE set worth trying against this host,
and it cost the caller nothing to obtain.

The fix gates those two fields on authentication rather than deleting
them, because they have a legitimate operator use and both are already
served to authenticated callers by `common_status()` (/v1/info,
/v1/status). What must NOT change:

* `version`, `loopback_only` and `exposed_publicly` stay public. The
  Android app reads exactly those three (`BridgeProbe.Status.of`) over
  an unauthenticated request -- it cannot read the token file, which
  lives under a different UID -- and #54 exists because that screen was
  starved of the exposure fact.
* The route keeps answering anonymous callers with 200. Probing auth
  must not refuse them and must not feed the brute-force throttle: an
  earlier draft that called `require_auth` here would have rate-limited
  the very poller this endpoint exists to serve.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import SystemHandlerContext  # noqa: E402
from arena.mobile import exposure_cache  # noqa: E402
from arena.system.handlers import make_system_handlers  # noqa: E402

TOKEN = "test-token-63"

# The fields whose disclosure this issue is about.
FINGERPRINT_FIELDS = ("python", "platform")


@pytest.fixture(autouse=True)
def _clean_memo():
    exposure_cache.reset()
    yield
    exposure_cache.reset()


def _call_version(tmp_path, *, headers=None):
    """Drive the real handler with the real auth probe.

    `check_auth` is the production function from the auth runtime, not a
    stub: a test that hand-waves authentication cannot show that an
    anonymous caller is treated as anonymous.
    """
    cfg = {"token": TOKEN, "bind": "127.0.0.1", "root": str(tmp_path)}
    app = ub.make_app(cfg)
    ctx = SystemHandlerContext(
        require_auth=ub.require_auth,
        record_request=lambda: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        common_status=lambda _cfg: {"ok": True},
        version=ub.VERSION,
        clean_platform_name=ub.get_clean_platform_name,
        doctor_sync=lambda token: {},
        sysinfo_sync=lambda root: {},
        play_beep_sync=lambda beep_type, freq, dur: {},
        send_notification_sync=lambda title, msg: {},
        check_auth=ub.check_auth,
    )
    handlers = make_system_handlers(ctx)
    request = make_mocked_request(
        "GET", "/v1/version", headers=headers or {}, app=app)
    with patch("arena.admin.auto_update._install_root", return_value=tmp_path):
        response = asyncio.run(handlers.version(request))
    return response, json.loads(response.text)


def _anonymous(tmp_path):
    return _call_version(tmp_path)


def _authenticated(tmp_path):
    return _call_version(tmp_path, headers={"Authorization": f"Bearer {TOKEN}"})


# --- the headline ----------------------------------------------------------


def test_anonymous_caller_gets_no_interpreter_or_os_build(tmp_path):
    """The live capture above, asserted."""
    _, body = _anonymous(tmp_path)

    for field in FINGERPRINT_FIELDS:
        assert field not in body, (
            f"unauthenticated /v1/version still publishes {field!r}="
            f"{body.get(field)!r}; that is the CVE-matching shortcut #63 "
            f"is about"
        )


def test_no_value_in_the_anonymous_body_reveals_the_python_build(tmp_path):
    """Not just the key: the value must be gone from the whole payload.

    Renaming the field, or folding the interpreter string into some
    other value, would pass the key check above while disclosing the
    same fact.
    """
    _, body = _anonymous(tmp_path)

    python_build = sys.version.split()[0]  # e.g. "3.14.7"
    blob = json.dumps(body)
    assert python_build not in blob, (
        f"the running interpreter build {python_build!r} still appears in "
        f"the anonymous response: {blob}"
    )


def test_authenticated_caller_still_gets_the_diagnostic(tmp_path):
    """Gated, not deleted -- the operator use survives."""
    _, body = _authenticated(tmp_path)

    assert body["python"] == sys.version.split()[0]
    assert body["platform"] == ub.get_clean_platform_name()


def test_deployment_record_follows_the_same_gate(tmp_path):
    """`deployment` is public-subset for anonymous, full for authenticated.

    `deployment_status(public=True)` deliberately drops the commit, the
    workflow run id and the archive digest -- v4.169.x kept those behind
    /v1/info and /v1/status. Passing `public=True` unconditionally here
    would silently withhold them from the operator who *did* present a
    token, which is the mirror-image mistake.
    """
    provenance = {
        "deploymentModel": "archive",
        "releaseTag": "v9.9.9",
        "installedAt": "2026-08-22T00:00:00Z",
        "authenticated": False,
        "sourceCommit": "deadbeef" * 5,
        "candidateRunId": "1234567890",
    }
    public_only = {
        "deploymentModel", "releaseTag", "installedAt", "authenticated"}

    with patch("arena.admin.deployment_provenance.read_deployed_provenance",
               return_value=provenance):
        _, anon = _anonymous(tmp_path)
        _, authed = _authenticated(tmp_path)

    assert set(anon["deployment"]) == public_only, (
        "the anonymous deployment record grew a field: "
        f"{sorted(set(anon['deployment']) - public_only)}"
    )
    assert anon["deployment"]["releaseTag"] == "v9.9.9"

    assert authed["deployment"]["sourceCommit"] == provenance["sourceCommit"]
    assert authed["deployment"]["candidateRunId"] == "1234567890"


# --- what must not regress -------------------------------------------------


def test_anonymous_caller_is_answered_not_refused(tmp_path):
    """Probing auth must not turn a public route into a refusal.

    `require_auth` returns 401 *and* records a failed attempt toward the
    10-in-60s throttle. Using it here would have broken the Android
    poller in two ways at once.
    """
    response, body = _anonymous(tmp_path)

    assert response.status == 200
    assert body["ok"] is True


def test_the_three_fields_android_reads_stay_public(tmp_path):
    """BridgeProbe.Status.of reads exactly these, with no token (#54)."""
    exposure_cache.record_tunnel_snapshot(
        {"tailscale": {"active": True, "connected": True,
                       "public_url": "https://pc.tail328f18.ts.net"}}
    )

    _, body = _anonymous(tmp_path)

    assert body["version"] == ub.VERSION, (
        "installers and the phone screen read the full version before they "
        "hold a token; /health and /v2/health publish it anyway"
    )
    assert body["loopback_only"] is True
    assert body["exposed_publicly"] is True, (
        "starving this field is the #54 regression"
    )


def test_a_bad_token_is_treated_as_anonymous(tmp_path):
    """A wrong credential must not unlock the gated fields."""
    _, body = _call_version(
        tmp_path, headers={"Authorization": "Bearer not-the-token"})

    for field in FINGERPRINT_FIELDS:
        assert field not in body


def test_a_broken_auth_probe_fails_closed(tmp_path):
    """If the probe raises, disclose less -- never more, never 500."""
    cfg = {"token": TOKEN, "bind": "127.0.0.1", "root": str(tmp_path)}
    app = ub.make_app(cfg)

    def _explode(_request):
        raise RuntimeError("auth backend down")

    ctx = SystemHandlerContext(
        require_auth=ub.require_auth,
        record_request=lambda: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        common_status=lambda _cfg: {"ok": True},
        version=ub.VERSION,
        clean_platform_name=ub.get_clean_platform_name,
        doctor_sync=lambda token: {},
        sysinfo_sync=lambda root: {},
        play_beep_sync=lambda beep_type, freq, dur: {},
        send_notification_sync=lambda title, msg: {},
        check_auth=_explode,
    )
    handlers = make_system_handlers(ctx)
    request = make_mocked_request(
        "GET", "/v1/version",
        headers={"Authorization": f"Bearer {TOKEN}"}, app=app)
    with patch("arena.admin.auto_update._install_root", return_value=tmp_path):
        response = asyncio.run(handlers.version(request))
    body = json.loads(response.text)

    assert response.status == 200
    for field in FINGERPRINT_FIELDS:
        assert field not in body


def test_missing_probe_defaults_to_minimal_disclosure(tmp_path):
    """A wiring mistake must not silently re-publish the fingerprint.

    `check_auth` is optional on the context so existing constructors keep
    working. Defaulting it to None must mean 'assume anonymous'.
    """
    cfg = {"token": TOKEN, "bind": "127.0.0.1", "root": str(tmp_path)}
    app = ub.make_app(cfg)
    ctx = SystemHandlerContext(
        require_auth=ub.require_auth,
        record_request=lambda: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        common_status=lambda _cfg: {"ok": True},
        version=ub.VERSION,
        clean_platform_name=ub.get_clean_platform_name,
        doctor_sync=lambda token: {},
        sysinfo_sync=lambda root: {},
        play_beep_sync=lambda beep_type, freq, dur: {},
        send_notification_sync=lambda title, msg: {},
    )
    handlers = make_system_handlers(ctx)
    request = make_mocked_request(
        "GET", "/v1/version",
        headers={"Authorization": f"Bearer {TOKEN}"}, app=app)
    with patch("arena.admin.auto_update._install_root", return_value=tmp_path):
        response = asyncio.run(handlers.version(request))
    body = json.loads(response.text)

    for field in FINGERPRINT_FIELDS:
        assert field not in body


# --- the wiring actually passes the probe ----------------------------------


def test_production_wiring_supplies_the_auth_probe():
    """The gate is dead code unless the real wiring passes `check_auth`.

    Without this, every assertion above would still pass while the live
    bridge published the fingerprint to the world -- the handler would
    simply never see a probe and treat the operator as anonymous too.
    """
    import inspect

    from arena.wiring import system_public_admin_registries as reg

    source = inspect.getsource(reg.build_system_public_admin_registries)
    assert "check_auth=env.check_auth" in source, (
        "system handler wiring no longer forwards check_auth; /v1/version "
        "would silently fall back to anonymous for everyone"
    )

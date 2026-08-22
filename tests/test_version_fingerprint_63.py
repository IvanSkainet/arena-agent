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


#: "argument not supplied", distinct from `check_auth=None` -- the latter
#: is the wiring slip this module exists to catch, so it must stay askable.
_UNSET = object()


def _call_version(tmp_path, *, headers=None, check_auth=_UNSET):
    """Drive the real handler with the real auth probe.

    `check_auth` defaults to the production function from the auth
    runtime, not a stub: a test that hand-waves authentication cannot
    show that an anonymous caller is treated as anonymous. Tests that
    need a broken or absent probe pass their own.
    """
    cfg = {"token": TOKEN, "bind": "127.0.0.1", "root": str(tmp_path)}
    app = ub.make_app(cfg)
    fields = dict(
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
    # `check_auth` is optional on the context and defaults to None there,
    # so "left off the constructor" is expressed by passing None -- which
    # a test must be able to ask for without it meaning "use the default".
    fields["check_auth"] = ub.check_auth if check_auth is _UNSET else check_auth
    ctx = SystemHandlerContext(**fields)
    handlers = make_system_handlers(ctx)
    request = make_mocked_request(
        "GET", "/v1/version", headers=headers or {}, app=app)
    with patch("arena.admin.auto_update._install_root", return_value=tmp_path):
        response = asyncio.run(handlers.version(request))
    return response, json.loads(response.text)


def _explode(_request):
    raise RuntimeError("auth backend down")


_BEARER = {"Authorization": f"Bearer {TOKEN}"}


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


def test_no_value_in_the_anonymous_body_reveals_the_host_fingerprint(tmp_path):
    """Not just the keys: the values must be gone from the whole payload.

    Renaming a field, or folding the interpreter or OS string into some
    other value, would pass the key checks above while disclosing the
    same fact. Both gated values are checked, since the PR gates both.
    """
    response, body = _anonymous(tmp_path)

    blob = json.dumps(body)
    raw = response.text.encode()
    for label, value in (
        ("interpreter build", sys.version.split()[0]),  # e.g. "3.14.7"
        ("OS build", ub.get_clean_platform_name()),
    ):
        assert value not in blob, (
            f"the running {label} {value!r} still appears in the anonymous "
            f"response: {blob}"
        )
        assert value.encode() not in raw, (
            f"the running {label} {value!r} still appears in the raw "
            f"anonymous response bytes"
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
    response, body = _call_version(
        tmp_path, headers=_BEARER, check_auth=_explode)

    assert response.status == 200
    for field in FINGERPRINT_FIELDS:
        assert field not in body


def test_missing_probe_defaults_to_minimal_disclosure(tmp_path):
    """A wiring mistake must not silently re-publish the fingerprint.

    `check_auth` is optional on the context so existing constructors keep
    working. Defaulting it to None must mean 'assume anonymous'.
    """
    _, body = _call_version(tmp_path, headers=_BEARER, check_auth=None)

    for field in FINGERPRINT_FIELDS:
        assert field not in body


# --- the wiring actually passes the probe ----------------------------------


def test_production_wiring_supplies_the_auth_probe():
    """The gate is dead code unless the real wiring passes `check_auth`.

    Without this, every assertion above would still pass while the live
    bridge published the fingerprint to the world -- the handler would
    simply never see a probe and treat the operator as anonymous too.

    Asserted by running the real wiring and inspecting the context it
    builds, rather than by grepping its source: reformatting or moving
    the argument must not fail this, and dropping it must.
    """
    from arena.wiring import system_public_admin_registries as reg

    sentinel = object()
    captured = {}

    def _capture(ctx):
        captured["ctx"] = ctx
        return {}

    g = dict(vars(ub))
    g["check_auth"] = sentinel
    g["build_system_handlers"] = _capture

    reg.build_system_public_admin_registries(g)

    assert captured, "the real wiring never built the system handlers"
    assert getattr(captured["ctx"], "check_auth", None) is sentinel, (
        "system handler wiring no longer forwards check_auth; /v1/version "
        "would silently fall back to anonymous for everyone"
    )


# --- the probe must not put disk I/O on a public route ---------------------


def test_anonymous_probe_does_no_per_request_disk_io(tmp_path):
    """Gating auth here must not make the public route touch the disk.

    `check_auth` used to fall straight through to `check_auth_with_role`,
    whose first act is `UserStore.load_users()`. With an empty roster the
    TTL cache was skipped (`and self._cache["users"]`), so the file was
    re-read every call: measured 100 reads per 100 calls. Harmless while
    only authenticated routes probed auth -- but /v1/version is public,
    unthrottled and polled by the phone, so this PR would have handed an
    anonymous caller a disk-I/O amplifier.
    """
    from arena.auth.users import UserStore

    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({"users": []}), encoding="utf-8")
    store = UserStore(users_file=users_file)

    reads = []
    real_read = Path.read_text

    def counting_read(self, *args, **kwargs):
        if self == users_file:
            reads.append(1)
        return real_read(self, *args, **kwargs)

    with patch.object(Path, "read_text", counting_read):
        for _ in range(50):
            store.load_users()

    assert len(reads) <= 1, (
        f"empty roster re-read {len(reads)} times in 50 calls; an empty "
        f"answer is still a cacheable answer"
    )


def test_credential_less_request_skips_the_roster_entirely(tmp_path):
    """No token presented -> no user lookup at all.

    Nothing in the roster can match a caller who presented nothing, so
    the lookup is pure cost on the public path.
    """
    app = ub.make_app(
        {"token": TOKEN, "bind": "127.0.0.1", "root": str(tmp_path)})
    request = make_mocked_request("GET", "/v1/version", app=app)

    with patch("arena.auth.users.UserStore.load_users") as loader:
        assert ub.check_auth(request) is False

    loader.assert_not_called()


def test_a_failing_probe_is_logged(tmp_path, caplog):
    """Failing closed silently would hide a broken auth backend."""
    with caplog.at_level("WARNING"):
        _call_version(tmp_path, headers=_BEARER, check_auth=_explode)

    assert any("auth probe failed" in r.message for r in caplog.records), (
        "a probe that raises must leave a trace for the operator"
    )

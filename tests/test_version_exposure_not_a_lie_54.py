"""`/v1/version` must not claim isolation while a funnel serves the request (#54).

The endpoint published `loopback_only`, computed from the bind address and
nothing else. That is a true statement about a socket and a false answer to
the question everyone actually asks it. Reproduced on the live bridge:

    $ tailscale funnel status
    # Funnel on:
    #     - https://pc.tail328f18.ts.net
    https://pc.tail328f18.ts.net (Funnel on)
    |-- / proxy http://127.0.0.1:8765

    $ curl http://127.0.0.1:8765/v1/version
    {"loopback_only": true, ...}

The response refuted itself: the request had arrived *through* that funnel.
Downstream, `BridgeProbe.loopbackOnly()` feeds `MainActivity`, which printed
"Direct access from other machines: no" for a bridge on the public internet.

Two constraints shape the fix, and each has tests here:

* **`/v1/version` is unauthenticated**, so it must not shell out.
  `tailscale funnel status` measured ~20 ms on the live bridge, which is a
  denial-of-service lever for anyone who can reach the port. The tunnel
  state comes from a memo filled by the authenticated paths that already
  pay for the probe.
* **Unknown is not false.** `exposed_publicly` is tri-state. "Nobody has
  looked recently" and "nothing is exposed" are different facts, and
  collapsing them is the very bug being fixed.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import SystemHandlerContext  # noqa: E402
from arena.mobile import exposure_cache  # noqa: E402
from arena.system.handlers import make_system_handlers  # noqa: E402

FUNNEL_UP = {
    "tailscale": {
        "active": True,
        "connected": True,
        "public_url": "https://pc.tail328f18.ts.net",
    }
}


@pytest.fixture(autouse=True)
def _clean_memo():
    exposure_cache.reset()
    yield
    exposure_cache.reset()


def _version_body(tmp_path, bind="127.0.0.1"):
    """Drive the real handler and return its parsed JSON."""
    ctx = SystemHandlerContext(
        require_auth=lambda _request: None,
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
    app = ub.make_app({"token": "test", "bind": bind, "root": str(tmp_path)})
    request = make_mocked_request("GET", "/v1/version", app=app)
    with patch("arena.admin.auto_update._install_root", return_value=tmp_path):
        response = asyncio.run(handlers.version(request))
    return json.loads(response.text)


# --- the headline: the endpoint stops contradicting itself ------------------


def test_version_reports_exposure_when_a_funnel_is_up(tmp_path):
    """The exact live scenario: loopback bind, funnel serving the request."""
    exposure_cache.record_tunnel_snapshot(FUNNEL_UP)

    body = _version_body(tmp_path)

    assert body["loopback_only"] is True, "the bind really is loopback"
    assert body["exposed_publicly"] is True, (
        "a funnel forwards from the public internet; saying nothing about it "
        "is how the Android screen ended up telling the operator the opposite"
    )


def test_version_says_not_exposed_when_every_tunnel_is_down(tmp_path):
    exposure_cache.record_tunnel_snapshot(
        {"tailscale": {"active": False, "connected": False, "public_url": None}}
    )

    body = _version_body(tmp_path)

    assert body["loopback_only"] is True
    assert body["exposed_publicly"] is False


def test_unknown_is_not_reported_as_safe(tmp_path):
    """Nobody has looked yet: that is null, never false.

    Reporting False here would be the original defect wearing a new field
    name -- a confident answer nobody checked.
    """
    body = _version_body(tmp_path)

    assert body["exposed_publicly"] is None, (
        "an unobserved bridge must not be reported as not exposed"
    )


def test_a_wide_bind_still_reports_its_own_fact(tmp_path):
    """`loopback_only` keeps its meaning; the new field is additive."""
    body = _version_body(tmp_path, bind="0.0.0.0")  # noqa: S104 - the point of the test

    assert body["loopback_only"] is False
    assert body["exposed_publicly"] is None, "a wide bind is not a tunnel"


# --- the unauthenticated endpoint must stay cheap ---------------------------


def test_version_never_shells_out_to_a_tunnel_provider(tmp_path):
    """~20 ms of subprocess on an unauthenticated route is a DoS lever."""
    exposure_cache.record_tunnel_snapshot(FUNNEL_UP)
    calls: list[list[str]] = []

    real_run = __import__("subprocess").run
    real_check = __import__("subprocess").check_output

    def spy_run(argv, *a, **k):
        calls.append(list(argv) if isinstance(argv, list) else [str(argv)])
        return real_run(argv, *a, **k)

    def spy_check(argv, *a, **k):
        calls.append(list(argv) if isinstance(argv, list) else [str(argv)])
        return real_check(argv, *a, **k)

    with patch("subprocess.run", spy_run), patch("subprocess.check_output", spy_check):
        body = _version_body(tmp_path)

    assert body["exposed_publicly"] is True
    assert calls == [], f"/v1/version launched a subprocess: {calls}"


def test_version_stays_answerable_when_nothing_ever_probed(tmp_path):
    """No memo, no provider call, still a well-formed answer."""
    body = _version_body(tmp_path)

    assert body["ok"] is True
    assert set(body) >= {"version", "loopback_only", "exposed_publicly"}


# --- the memo itself --------------------------------------------------------


def test_a_stale_observation_expires_instead_of_lying():
    """A funnel that stopped must not be reported as up forever."""
    exposure_cache.record_tunnel_snapshot(FUNNEL_UP)
    fresh = exposure_cache.exposure_snapshot()
    assert fresh["exposed"] is True

    later = time.monotonic() + exposure_cache.EXPOSURE_TTL_S + 1
    stale = exposure_cache.exposure_snapshot(now=later)

    assert stale["exposed"] is None, "an expired memo must degrade to unknown"
    assert stale["age_s"] is None


def test_an_observation_inside_the_window_is_still_trusted():
    exposure_cache.record_tunnel_snapshot(FUNNEL_UP)

    snap = exposure_cache.exposure_snapshot(
        now=time.monotonic() + exposure_cache.EXPOSURE_TTL_S - 1
    )

    assert snap["exposed"] is True
    assert snap["age_s"] is not None and snap["age_s"] > 0


def test_a_clock_that_moves_backwards_does_not_produce_a_fact(tmp_path):
    """A negative age is nonsense; degrade rather than assert the past."""
    exposure_cache.record_tunnel_snapshot(FUNNEL_UP)

    snap = exposure_cache.exposure_snapshot(now=time.monotonic() - 30)

    assert snap["exposed"] is None


@pytest.mark.parametrize(
    ("snapshot", "expected", "why"),
    [
        ({"ngrok": {"active": True, "public_url": "https://x.ngrok.dev"}}, True,
         "active with a URL is exposure"),
        ({"ngrok": {"connected": True, "public_url": "https://x.ngrok.dev"}}, True,
         "connected with a URL counts too, as access_info decides it"),
        ({"ngrok": {"active": True, "public_url": None}}, False,
         "no URL means nothing forwards"),
        ({"ngrok": {"active": False, "connected": False,
                    "public_url": "https://x.ngrok.dev"}}, False,
         "installed but idle is not exposure"),
        ({}, False, "no providers at all"),
        ({"ngrok": "not-a-dict"}, False, "a malformed entry is not exposure"),
    ],
)
def test_what_counts_as_exposure_matches_access_info(snapshot, expected, why):
    exposure_cache.record_tunnel_snapshot(snapshot)

    assert exposure_cache.exposure_snapshot()["exposed"] is expected, why


def test_the_exposing_providers_are_named():
    """"Something is exposed" is less useful than saying which thing."""
    exposure_cache.record_tunnel_snapshot(
        {
            "tailscale": {"active": True, "public_url": "https://a.ts.net"},
            "ngrok": {"active": False, "public_url": "https://b.ngrok.dev"},
        }
    )

    assert exposure_cache.exposure_snapshot()["providers"] == ("tailscale",)


def test_a_later_observation_replaces_an_earlier_one():
    """Stopping a funnel must be visible, not merely un-refreshed."""
    exposure_cache.record_tunnel_snapshot(FUNNEL_UP)
    exposure_cache.record_tunnel_snapshot(
        {"tailscale": {"active": False, "connected": False, "public_url": None}}
    )

    assert exposure_cache.exposure_snapshot()["exposed"] is False


def test_garbage_input_does_not_wedge_the_memo():
    exposure_cache.record_tunnel_snapshot(None)
    assert exposure_cache.exposure_snapshot()["exposed"] is False

    exposure_cache.record_tunnel_snapshot("nonsense")  # type: ignore[arg-type]
    assert exposure_cache.exposure_snapshot()["exposed"] is False


# --- the memo is actually filled by the authenticated callers ---------------


def test_tunnels_status_handler_records_what_it_learned():
    """Without this wiring the memo is always empty and the fix is inert."""
    from arena.admin.handlers import _record_exposure

    _record_exposure({"providers": FUNNEL_UP})

    assert exposure_cache.exposure_snapshot()["exposed"] is True


def test_the_list_shaped_provider_snapshot_is_understood():
    """`tunnels_status` has produced both shapes; handlers_access handles both."""
    from arena.admin.handlers import _record_exposure

    _record_exposure(
        {"providers": [{"provider": "tailscale", "active": True,
                        "public_url": "https://a.ts.net"}]}
    )

    assert exposure_cache.exposure_snapshot()["exposed"] is True


def test_recording_never_breaks_the_response_it_rides_on():
    """Bookkeeping is not worth a 500 on the endpoint the caller wanted."""
    from arena.admin.handlers import _record_exposure

    class Hostile:
        def get(self, *_a, **_k):
            raise RuntimeError("provider blew up")

    _record_exposure(Hostile())  # must not raise

    assert exposure_cache.exposure_snapshot()["exposed"] is None


def test_the_tunnels_status_handler_actually_calls_the_recorder():
    """Testing the helper is not testing the wiring.

    A sabotage run that deleted the `_record_exposure(result)` call from
    `handle_v1_tunnels_status` left every test green: the helper was still
    covered, and nothing asserted the handler reached it. Drive the real
    handler and watch the memo change.
    """
    import functools

    from arena.admin import handlers as admin_handlers

    recorded: list[dict] = []

    def fake_record(snapshot):
        recorded.append(snapshot)

    class _Ctx:
        executor = None
        sys_funnel_status_sync = None
        cloudflared_status_sync = None
        zerotier_status_sync = None
        ngrok_status_sync = None
        bore_status_sync = None

        @staticmethod
        def cors_json_response(payload, status=200):
            return payload

        @staticmethod
        def require_auth(_request):
            return None

        @staticmethod
        def record_request():
            return None

    def fake_tunnels_status(**_kwargs):
        return {"providers": FUNNEL_UP}

    with patch.object(admin_handlers, "tunnels_status", fake_tunnels_status), \
         patch.object(admin_handlers, "record_tunnel_snapshot", fake_record):
        handlers = admin_handlers.make_admin_handlers(_Ctx())
        handler = handlers.tunnels_status
        app = ub.make_app({"token": "test", "bind": "127.0.0.1", "port": 8765})
        request = make_mocked_request(
            "GET", "/v1/tunnels/status",
            headers={"Authorization": "Bearer test"}, app=app,
        )
        asyncio.run(handler(request))

    assert recorded, (
        "handle_v1_tunnels_status probed the providers and did not publish "
        "the result, so /v1/version keeps answering unknown forever"
    )
    assert recorded[0] == FUNNEL_UP
    del functools


def test_the_access_handler_feeds_the_same_memo():
    """/v1/access already probes providers; it must publish them too."""
    source = Path(__file__).resolve().parents[1] / "arena/admin/handlers_access.py"
    text = source.read_text(encoding="utf-8")

    assert "record_tunnel_snapshot(tunnels)" in text, (
        "/v1/access pays for a provider probe and throws the answer away"
    )


def test_a_malformed_provider_does_not_hide_the_ones_after_it():
    """`continue`, not `break`: one bad entry must not end the scan.

    Mutation flagged this: turning the skip into a `break` left every test
    green, and a bridge whose first provider serialised oddly would have
    reported "not exposed" with a live funnel sitting behind it.
    """
    exposure_cache.record_tunnel_snapshot(
        {
            "broken": "not-a-dict",
            "idle": {"active": False, "public_url": None},
            "tailscale": {"active": True, "public_url": "https://a.ts.net"},
        }
    )

    snap = exposure_cache.exposure_snapshot()

    assert snap["exposed"] is True
    assert snap["providers"] == ("tailscale",)


def test_a_provider_without_a_url_does_not_stop_the_scan():
    exposure_cache.record_tunnel_snapshot(
        {
            "aaa_no_url": {"active": True, "public_url": None},
            "zzz_real": {"active": True, "public_url": "https://z.ts.net"},
        }
    )

    assert exposure_cache.exposure_snapshot()["providers"] == ("zzz_real",)


def test_the_snapshot_keys_are_the_contract():
    """The handler indexes these by name; a typo would read as unknown."""
    exposure_cache.record_tunnel_snapshot(FUNNEL_UP)

    assert set(exposure_cache.exposure_snapshot()) == {
        "exposed", "providers", "age_s"
    }
    assert set(exposure_cache.exposure_snapshot(now=time.monotonic() + 1e6)) == {
        "exposed", "providers", "age_s"
    }


def test_an_observation_exactly_at_the_ttl_is_still_valid():
    """The boundary is `>`, not `>=`: pin it so it cannot drift silently."""
    exposure_cache.record_tunnel_snapshot(FUNNEL_UP)
    at = exposure_cache._STATE["at"]

    assert exposure_cache.exposure_snapshot(
        now=at + exposure_cache.EXPOSURE_TTL_S
    )["exposed"] is True
    assert exposure_cache.exposure_snapshot(
        now=at + exposure_cache.EXPOSURE_TTL_S + 0.001
    )["exposed"] is None


def test_reset_clears_every_field():
    """A half-cleared memo would resurrect a stale provider list."""
    exposure_cache.record_tunnel_snapshot(FUNNEL_UP)
    exposure_cache.reset()

    assert exposure_cache.exposure_snapshot() == {
        "exposed": None, "providers": (), "age_s": None
    }
    assert exposure_cache._STATE["providers"] == ()
    assert exposure_cache._STATE["exposed"] is None
    assert exposure_cache._STATE["at"] == 0.0


def test_an_observation_read_in_the_same_instant_is_valid():
    """Age zero is fresh, not stale.

    A phone that polls /v1/version in the same tick as the status call
    that filled the memo must see the answer, not "unknown".
    """
    exposure_cache.record_tunnel_snapshot(FUNNEL_UP)
    at = exposure_cache._STATE["at"]

    snap = exposure_cache.exposure_snapshot(now=at)

    assert snap["exposed"] is True
    assert snap["age_s"] == 0.0


def test_the_unknown_answer_cannot_be_mutated_by_a_caller():
    """Handlers get a fresh dict; one scribbling on it must not poison
    the next reader."""
    first = exposure_cache.exposure_snapshot()
    first["exposed"] = True
    first["providers"] = ("bogus",)

    assert exposure_cache.exposure_snapshot() == {
        "exposed": None, "providers": (), "age_s": None
    }


def test_a_failed_recording_is_swallowed_but_not_silent(caplog):
    """Bookkeeping must not break the response -- and must not vanish.

    If recording ever starts throwing, /v1/version answers "unknown"
    forever. A bare `except: pass` would make that state indistinguishable
    from a bridge nobody has probed yet.
    """
    from arena.admin import handlers as admin_handlers

    def boom(_snapshot):
        raise RuntimeError("disk on fire")

    with patch.object(admin_handlers, "record_tunnel_snapshot", boom):
        with caplog.at_level("WARNING"):
            admin_handlers._record_exposure({"providers": FUNNEL_UP})

    assert any(
        "exposure" in rec.message for rec in caplog.records
    ), "the failure was swallowed without a trace"


# --- the Android client, which is where the lie was actually read -------

_APP_SRC = (
    Path(__file__).resolve().parents[1]
    / "android_app" / "src" / "ai" / "arena" / "bridge"
)


def _java(name: str) -> str:
    return (_APP_SRC / name).read_text(encoding="utf-8")


def test_the_phone_reads_the_new_field():
    """Fixing the server alone leaves the operator reading the old lie.

    The status screen said "Direct access from other machines: no" on a
    phone whose Funnel was live, because it only ever asked about the
    bind. It has to read the exposure field too or the defect is still
    on screen.
    """
    probe = _java("BridgeProbe.java")
    activity = _java("MainActivity.java")

    assert "exposed_publicly" in probe
    assert "exposedPublicly" in activity, (
        "MainActivity still renders the bind alone; the exposure answer "
        "never reaches the screen"
    )


def test_the_phone_never_reads_unknown_as_no():
    """`null` and `false` are different answers on this screen."""
    probe = _java("BridgeProbe.java")
    body = probe[probe.index("static Boolean tristate("):]
    body = body[: body.index("\n    }")]

    assert '"null".equals(value)' in body, (
        "a JSON null would parse as not-true and render as 'no tunnel', "
        "which is the same conflation this issue is about"
    )
    assert '"true".equals(value)' in body
    assert '"false".equals(value)' in body


def test_the_status_screen_asks_once():
    """Three probes meant three instants and a screen that could show a
    combination which was never true at any single moment."""
    activity = _java("MainActivity.java")

    calls = [
        line for line in activity.splitlines()
        if "BridgeProbe.status()" in line and "//" not in line.split("BridgeProbe")[0]
    ]
    assert len(calls) == 1, calls
    for gone in ("BridgeProbe.loopbackOnly()", "BridgeProbe.exposedPublicly()"):
        assert gone not in activity, f"{gone} costs an extra round trip"


def test_the_screen_states_internet_reachability_separately():
    """The bind line and the tunnel line are different facts."""
    activity = _java("MainActivity.java")

    assert "Reachable from the internet" in activity
    at_bind = activity.index("Direct access from other machines")
    at_net = activity.index("Reachable from the internet")
    assert at_net > at_bind, "the exposure line must not replace the bind line"

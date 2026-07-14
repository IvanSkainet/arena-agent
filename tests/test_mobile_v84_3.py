"""Tests for v3.84.3: live H.264 mirror + WS token auth.

Full end-to-end mirror is exercised by scripts/smoke_mobile.py against
a real device (uses websockets + ffmpeg). Here we cover the parts that
can be tested without a phone or subprocesses: helper math, session
registry lifecycle, and auth acceptance of `?token=` query."""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# mirror.MirrorSession — subscriber fanout + backpressure
# ---------------------------------------------------------------------------
def test_mirror_session_broadcasts_to_all_subscribers():
    """A chunk fanned out reaches every subscriber's queue."""
    from arena.mobile import mirror as _m
    session = _m.MirrorSession(serial="dummy", size="720x1600",
                               bit_rate=4_000_000)
    q1 = session.add_subscriber()
    q2 = session.add_subscriber()
    session.broadcast(b"chunk-A")
    session.broadcast(b"chunk-B")
    assert q1.qsize() == 2
    assert q2.qsize() == 2
    assert session.fragments_sent == 2
    assert session.bytes_sent == len(b"chunk-A") + len(b"chunk-B")


def test_mirror_session_drops_frame_when_subscriber_queue_full():
    """Slow subscribers must not block the pipeline for everyone else.
    Bounded asyncio.Queue(maxsize=32) will raise QueueFull under
    put_nowait, and the broadcast should swallow it."""
    from arena.mobile import mirror as _m
    session = _m.MirrorSession(serial="dummy", size="720x1600",
                               bit_rate=4_000_000)
    q_slow = session.add_subscriber()
    q_fast = session.add_subscriber()
    # Fill the slow queue past its 32-frame ceiling.
    for i in range(50):
        session.broadcast(b"x")
    # Fast subscriber must still have all 50 in its queue
    # (asyncio.Queue.qsize can be at most 32, so this asserts the
    # cap works — 32 is the ceiling).
    assert q_fast.qsize() == 32
    assert q_slow.qsize() == 32
    # And session bytes_sent counts every broadcast, not per-subscriber.
    assert session.fragments_sent == 50


def test_mirror_session_remove_subscriber():
    from arena.mobile import mirror as _m
    session = _m.MirrorSession(serial="dummy", size="720x1600",
                               bit_rate=4_000_000)
    q = session.add_subscriber()
    assert session.has_subscribers()
    session.remove_subscriber(q)
    assert not session.has_subscribers()


# ---------------------------------------------------------------------------
# mirror.get_or_start — registry lookup semantics
# ---------------------------------------------------------------------------
def test_mirror_get_or_start_returns_same_session_for_same_serial(monkeypatch):
    """Two calls with the same serial share ONE session — a second
    Dashboard tab does not spawn a second ffmpeg pipeline."""
    from arena.mobile import mirror as _m
    _m._SESSIONS.clear()

    # Stub out the pipeline coroutine so we don't spawn subprocesses.
    async def _no_pipeline(session, loop):
        pass
    monkeypatch.setattr(_m, "_pump_pipeline", _no_pipeline)
    monkeypatch.setattr(_m, "find_adb", lambda: "/usr/bin/adb")
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        s1 = _m.get_or_start("dummy", loop=loop)
        s2 = _m.get_or_start("dummy", loop=loop)
        assert s1 is s2
    finally:
        loop.close()
        _m._SESSIONS.clear()


def test_mirror_get_or_start_different_serials_get_different_sessions(monkeypatch):
    from arena.mobile import mirror as _m
    _m._SESSIONS.clear()
    async def _no_pipeline(session, loop):
        pass
    monkeypatch.setattr(_m, "_pump_pipeline", _no_pipeline)
    monkeypatch.setattr(_m, "find_adb", lambda: "/usr/bin/adb")
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        s1 = _m.get_or_start("phone-a", loop=loop)
        s2 = _m.get_or_start("phone-b", loop=loop)
        assert s1 is not s2
        assert s1.serial == "phone-a"
        assert s2.serial == "phone-b"
    finally:
        loop.close()
        _m._SESSIONS.clear()


def test_mirror_stats_reports_all_sessions(monkeypatch):
    from arena.mobile import mirror as _m
    _m._SESSIONS.clear()
    async def _no_pipeline(session, loop):
        pass
    monkeypatch.setattr(_m, "_pump_pipeline", _no_pipeline)
    monkeypatch.setattr(_m, "find_adb", lambda: "/usr/bin/adb")
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        _m.get_or_start("dummy-a", loop=loop, size="540x1200", bit_rate=1_000_000)
        _m.get_or_start("dummy-b", loop=loop, size="1080x2400", bit_rate=8_000_000)
        stats = _m.stats()
        serials = {s["serial"] for s in stats}
        assert serials == {"dummy-a", "dummy-b"}
        a = next(s for s in stats if s["serial"] == "dummy-a")
        assert a["size"] == "540x1200"
        assert a["bit_rate"] == 1_000_000
        assert a["subscribers"] == 0
    finally:
        loop.close()
        _m._SESSIONS.clear()


# ---------------------------------------------------------------------------
# mirror pipeline commands — regression guard on the ffmpeg args
# ---------------------------------------------------------------------------
def test_screenrecord_cmd_shape():
    """Backend must invoke screenrecord with the exact flags that make
    a NAL stream (not MP4)."""
    from arena.mobile.mirror import _screenrecord_cmd
    cmd = _screenrecord_cmd("2200ad3b", "720x1600", 4_000_000)
    joined = " ".join(cmd)
    assert "exec-out" in cmd and "screenrecord" in cmd
    assert "--output-format=h264" in joined
    assert "--size" in cmd and "720x1600" in cmd
    assert "--bit-rate" in cmd and "4000000" in cmd
    assert cmd[-1] == "-", "screenrecord must write to stdout"


def test_ffmpeg_cmd_has_fragmented_mp4_flags():
    """Regression: MSE needs empty_moov + separate_moof + frag_keyframe.
    Missing any of them breaks the browser <video> playback."""
    from arena.mobile.mirror import _ffmpeg_cmd
    cmd = _ffmpeg_cmd()
    joined = " ".join(cmd)
    assert "-c:v" in cmd and "copy" in cmd, "must not re-encode"
    assert "empty_moov" in joined
    assert "separate_moof" in joined
    assert "frag_keyframe" in joined
    assert "-f mp4" in joined
    assert cmd[-1] == "pipe:1"


# ---------------------------------------------------------------------------
# Auth: v3.84.3 added `?token=` query support for WebSocket handshakes
# ---------------------------------------------------------------------------
def test_check_auth_accepts_query_token(monkeypatch):
    """Browsers can't set Authorization on a WS upgrade — the check_auth
    runtime now accepts a `?token=` query param as a third option.
    Test at the module level (not a real WS) since aiohttp app/request
    plumbing is complex to set up in-process."""
    import hmac
    from types import SimpleNamespace
    # Build a fake request that only carries the query param.
    class _FakeReq:
        def __init__(self, query=None, headers=None):
            self.query = query or {}
            self.headers = headers or {}
            self.app = {
                # APP_CFG key value from arena.auth.runtime
                "arena.app_cfg": {"token": "secret-123"}
            }
    # `check_auth` reads request.app[APP_CFG]; import APP_CFG constant.
    from arena.auth.runtime import APP_CFG, make_auth_runtime, AuthRuntimeContext
    # Build a minimal user_store stub.
    stub_store = SimpleNamespace(
        load_users=lambda: {},
        check_auth_with_role=lambda req, required_role=None: (False, ""),
    )
    ctx = AuthRuntimeContext(
        user_store=stub_store,
        rate_limit_lock=__import__("threading").Lock(),
        rate_limit_store={},
        now=lambda: 0.0,
        log_warning=lambda *a, **k: None,
        cors_json_response=lambda payload, status=200, extra_headers=None:
            SimpleNamespace(status=status, payload=payload),
    )
    runtime = make_auth_runtime(ctx)
    # Wrap request.app to use APP_CFG constant properly.
    req = _FakeReq(query={"token": "secret-123"})
    req.app = {APP_CFG: {"token": "secret-123"}}
    assert runtime.check_auth(req) is True
    # Wrong token in query → still fails.
    req2 = _FakeReq(query={"token": "wrong"})
    req2.app = {APP_CFG: {"token": "secret-123"}}
    assert runtime.check_auth(req2) is False
    # No token at all → still fails.
    req3 = _FakeReq()
    req3.app = {APP_CFG: {"token": "secret-123"}}
    assert runtime.check_auth(req3) is False


# ---------------------------------------------------------------------------
# Handler dataclass — v3.84.3 exact 41-field surface
# ---------------------------------------------------------------------------
def test_mobile_handlers_dataclass_fields_v84_3():
    """v3.84.3 baseline: check the 41-field surface stays available.
    Newer releases add fields; this test keeps them as a required subset
    so a regression that drops any of these still trips the suite."""
    from arena.mobile.handlers import MobileHandlers
    required = {
        "list_devices", "device_info", "screenshot", "tap", "swipe",
        "type_text", "key_event", "shell", "packages", "gesture",
        "ui_dump", "tap_by",
        "helpers_status", "helpers_install",
        "ime_status", "ime_set", "ime_reset", "paste",
        "sensors", "scroll", "key_combo",
        "pair", "connect", "disconnect", "apk_prepare", "apk_install",
        "batch",
        "camera_launch", "camera_shutter", "camera_photos",
        "camera_pull", "camera_capture",
        "apk_upload",
        "record_sync", "record_start", "record_stop",
        "record_list", "record_pull", "record_purge",
        "mirror_ws", "mirror_stats", "mirror_stop",
    }
    got = {f.name for f in MobileHandlers.__dataclass_fields__.values()}
    missing = required - got
    assert not missing, f"MobileHandlers regressed: dropped {missing}"


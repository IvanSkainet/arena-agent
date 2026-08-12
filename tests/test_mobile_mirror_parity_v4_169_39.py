"""v4.169.39 -- arena.mobile.mirror parity tests (mutation-driven).

Fast, deterministic tests with full mock isolation targeting 100% mutation kill rate for
`arena/mobile/mirror.py`:
* Stream parameter validation (`validate_stream_params` boundaries, regexes, types);
* `_screenrecord_cmd` generation, parameter forwarding, find_adb fallback, ValueError on bad input;
* `MirrorSession` subscriber lifecycle (seed on join with init/keyframe, remove, broadcast counting, QueueFull handling);
* Pipeline pump callbacks (`_on_init`, `_on_fragment`), keyframe tracking, timeout on no first subscriber;
* Process management (spawn, read loop, stop_event, EOF, cleanup from `_SESSIONS`);
* `get_or_start`, `stop_all`, `stats` registry contracts;
* HTTP/WebSocket handlers (`handle_mirror_ws`, `handle_mirror_stats`, `handle_mirror_stop`):
  - Auth enforcement on all handlers;
  - Missing serial (400), missing ADB (503), parameter validation failure (400);
  - Control marker translation (`_INIT_MARKER` -> "__init__" text frame, payload -> binary frame);
  - Auditing on subscribe and stop.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.mobile.mirror as mirror  # noqa: E402
from arena.mobile.mirror import (  # noqa: E402
    _INIT_MARKER,
    _MAX_BITRATE,
    _MIN_BITRATE,
    _SEGMENT_SECONDS,
    DEFAULT_BIT_RATE,
    DEFAULT_SIZE,
    MirrorSession,
    _screenrecord_cmd,
    get_or_start,
    make_mirror_handlers,
    stats,
    stop_all,
    validate_stream_params,
)


class _MockContext:
    def __init__(self, reject_auth: bool = False) -> None:
        self.reject_auth = reject_auth
        self.auth_calls: list[Any] = []
        self.audit_events: list[dict[str, Any]] = []

    def require_auth(self, request: Any) -> Any:
        self.auth_calls.append(request)
        if self.reject_auth or request.headers.get("Authorization") != "Bearer t":
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        return None

    def audit(self, event: dict[str, Any]) -> None:
        self.audit_events.append(dict(event))


def _cors_response(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


@pytest.fixture(autouse=True)
def _clear_sessions():
    with mirror._SESSIONS_LOCK:
        mirror._SESSIONS.clear()
    yield
    with mirror._SESSIONS_LOCK:
        mirror._SESSIONS.clear()


# ---------------------------------------------------------------------------
# validate_stream_params & _screenrecord_cmd
# ---------------------------------------------------------------------------

def test_validate_stream_params_valid():
    assert validate_stream_params("720x1600", 4_000_000) is None
    assert validate_stream_params("10x10", 100_000) is None
    assert validate_stream_params("1920x1080", 100_000_000) is None


@pytest.mark.parametrize("size", [
    "", "abc", "0x1600", "720x0", "720x", "x1600", "-720x1600",
    "720x1600; touch /tmp/pwned", 123, None, "01x10", "100000x100000"
])
def test_validate_stream_params_invalid_size(size):
    err = validate_stream_params(size, 4_000_000)
    assert err is not None
    assert "size must be WxH" in err


@pytest.mark.parametrize("bit_rate", [
    _MIN_BITRATE - 1, _MAX_BITRATE + 1, -1, 0, "4000000", None, 4000000.5
])
def test_validate_stream_params_invalid_bitrate(bit_rate):
    err = validate_stream_params("720x1600", bit_rate)
    assert err is not None
    assert "bit_rate out of range" in err


def test_screenrecord_cmd_valid():
    with patch("arena.mobile.mirror.find_adb", return_value="/opt/bin/adb"):
        cmd = _screenrecord_cmd("emulator-5554", "1080x2400", 6_000_000)
        assert cmd == [
            "/opt/bin/adb", "-s", "emulator-5554",
            "exec-out", "screenrecord",
            "--output-format=h264",
            "--time-limit", str(_SEGMENT_SECONDS),
            "--size", "1080x2400",
            "--bit-rate", "6000000",
            "-",
        ]

    # find_adb fallback to "adb"
    with patch("arena.mobile.mirror.find_adb", return_value=None):
        cmd = _screenrecord_cmd("phone-1", "720x1600", 4_000_000)
        assert cmd[0] == "adb"


def test_screenrecord_cmd_invalid_raises():
    with pytest.raises(ValueError, match="size must be WxH"):
        _screenrecord_cmd("phone-1", "invalid_size", 4_000_000)


# ---------------------------------------------------------------------------
# MirrorSession Subscriber & Broadcast Lifecycle
# ---------------------------------------------------------------------------

def test_mirror_session_subscriber_lifecycle():
    session = MirrorSession(serial="dev-1", size=DEFAULT_SIZE, bit_rate=DEFAULT_BIT_RATE)
    assert not session.has_subscribers()
    assert not session.first_subscriber.is_set()

    # Add subscriber when no cache exists
    q1 = session.add_subscriber()
    assert session.has_subscribers()
    assert session.first_subscriber.is_set()
    assert q1.empty()

    # Add subscriber when last_init is present
    session.last_init = b"init_bytes"
    q2 = session.add_subscriber()
    assert q2.get_nowait() == _INIT_MARKER
    assert q2.get_nowait() == b"init_bytes"
    assert q2.empty()

    # Add subscriber when last_init and last_keyframe are present
    session.last_keyframe = b"keyframe_bytes"
    q3 = session.add_subscriber()
    assert q3.get_nowait() == _INIT_MARKER
    assert q3.get_nowait() == b"init_bytes"
    assert q3.get_nowait() == b"keyframe_bytes"
    assert q3.empty()

    # Remove subscriber
    session.remove_subscriber(q1)
    session.remove_subscriber(q2)
    session.remove_subscriber(q3)
    assert not session.has_subscribers()


def test_mirror_session_broadcast_and_queue_full():
    session = MirrorSession(serial="dev-1", size=DEFAULT_SIZE, bit_rate=DEFAULT_BIT_RATE)
    q = session.add_subscriber()

    # Control marker broadcast -> does not increment counters
    session.broadcast(_INIT_MARKER)
    assert q.get_nowait() == _INIT_MARKER
    assert session.fragments_sent == 0
    assert session.bytes_sent == 0

    # Data chunk broadcast -> increments counters
    data = b"chunk_12345"
    session.broadcast(data)
    assert q.get_nowait() == data
    assert session.fragments_sent == 1
    assert session.bytes_sent == len(data)

    # Queue full handling: fill queue to capacity (maxsize=32)
    for _ in range(32):
        q.put_nowait(b"fill")
    # Next broadcast should not raise QueueFull
    session.broadcast(b"overflow")
    assert session.fragments_sent == 2
    assert session.bytes_sent == len(data) + len(b"overflow")


# ---------------------------------------------------------------------------
# get_or_start, stop_all, stats registry
# ---------------------------------------------------------------------------

def test_get_or_start_and_stats_and_stop_all():
    loop = asyncio.new_event_loop()
    try:
        with patch("arena.mobile.mirror._pump_pipeline") as mock_pump:
            async def _dummy(s):
                pass
            mock_pump.side_effect = _dummy

            s1 = get_or_start("serial-A", size="720x1600", bit_rate=3_000_000, loop=loop)
            assert s1.serial == "serial-A"
            assert s1.size == "720x1600"
            assert s1.bit_rate == 3_000_000

            # Second call returns existing session
            s2 = get_or_start("serial-A", loop=loop)
            assert s1 is s2

            st = stats()
            assert len(st) == 1
            assert st[0]["serial"] == "serial-A"
            assert st[0]["size"] == "720x1600"
            assert st[0]["bit_rate"] == 3_000_000
            assert st[0]["muxer"] == "python-native"
            assert st[0]["subscribers"] == 0

            assert not s1.stop_event.is_set()
            stop_all()
            assert s1.stop_event.is_set()
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# _pump_pipeline logic & callbacks
# ---------------------------------------------------------------------------

def test_pump_pipeline_timeout_when_no_first_subscriber():
    session = MirrorSession(serial="serial-timeout", size=DEFAULT_SIZE, bit_rate=DEFAULT_BIT_RATE)
    with mirror._SESSIONS_LOCK:
        mirror._SESSIONS[session.serial] = session

    with patch("arena.mobile.mirror._FIRST_SUBSCRIBER_TIMEOUT", 0.01):
        asyncio.run(mirror._pump_pipeline(session))

    # Session should have cleaned itself up from registry
    with mirror._SESSIONS_LOCK:
        assert session.serial not in mirror._SESSIONS


def test_pump_pipeline_on_init_and_on_fragment_callbacks():
    session = MirrorSession(serial="serial-cb", size=DEFAULT_SIZE, bit_rate=DEFAULT_BIT_RATE)
    session.add_subscriber()
    assert session.first_subscriber.is_set()

    # Emulate process mock
    class _MockProcess:
        def __init__(self):
            self.stdout = AsyncMock()
            self.stdout.read = AsyncMock(side_effect=[b"h264_frame_data", b""])
            self.stderr = AsyncMock()
            self.stderr.readline = AsyncMock(side_effect=[b"info line\n", b""])
            self.terminate = MagicMock()
            self.kill = MagicMock()
            self.wait = AsyncMock(return_value=0)

    mock_proc = _MockProcess()

    # Capture H264ToFMP4 init/fragment callbacks
    captured_callbacks = {}

    def _mock_h264_init(on_init, on_fragment):
        captured_callbacks["on_init"] = on_init
        captured_callbacks["on_fragment"] = on_fragment
        mock_mux = MagicMock()
        mock_mux.reset = MagicMock()
        mock_mux.feed = MagicMock()
        mock_mux.flush = MagicMock()
        return mock_mux

    with patch("arena.mobile.mirror.H264ToFMP4", side_effect=_mock_h264_init), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)), \
         patch("arena.mobile.mirror._READ_POLL_SECONDS", 0.01):

        # Trigger on_init
        async def _run_test():
            task = asyncio.create_task(mirror._pump_pipeline(session))
            await asyncio.sleep(0.02)

            on_init = captured_callbacks["on_init"]
            on_fragment = captured_callbacks["on_fragment"]

            # 1. On init segment
            on_init(b"init_segment_data")
            assert session.last_init == b"init_segment_data"
            assert session.last_keyframe is None

            # 2. On fragment (non-keyframe)
            on_fragment(b"frag_p_frame", is_keyframe=False)
            assert session.keyframes_sent == 0
            assert session.last_keyframe is None

            # 3. On fragment (keyframe)
            on_fragment(b"frag_idr_frame", is_keyframe=True)
            assert session.keyframes_sent == 1
            assert session.last_keyframe == b"frag_idr_frame"

            session.stop_event.set()
            await task

        asyncio.run(_run_test())


# ---------------------------------------------------------------------------
# HTTP & WebSocket Handlers
# ---------------------------------------------------------------------------

def test_make_mirror_handlers_keys():
    ctx = _MockContext()
    handlers = make_mirror_handlers(ctx, cors=_cors_response)
    expected = {"mirror_ws", "mirror_stats", "mirror_stop"}
    assert set(handlers.keys()) == expected
    for k in expected:
        assert callable(handlers[k])


def test_mirror_handlers_auth_enforcement():
    ctx = _MockContext(reject_auth=True)
    handlers = make_mirror_handlers(ctx, cors=_cors_response)

    req_ws = make_mocked_request("GET", "/v1/mobile/dev1/mirror/ws", headers={})
    resp_ws = asyncio.run(handlers["mirror_ws"](req_ws))
    assert resp_ws.status == 401

    req_stats = make_mocked_request("GET", "/v1/mobile/mirror/stats", headers={})
    resp_stats = asyncio.run(handlers["mirror_stats"](req_stats))
    assert resp_stats.status == 401

    req_stop = make_mocked_request("POST", "/v1/mobile/dev1/mirror/stop", headers={})
    resp_stop = asyncio.run(handlers["mirror_stop"](req_stop))
    assert resp_stop.status == 401


def test_handle_mirror_stats_ok():
    ctx = _MockContext()
    handlers = make_mirror_handlers(ctx, cors=_cors_response)
    req = make_mocked_request("GET", "/v1/mobile/mirror/stats", headers={"Authorization": "Bearer t"})

    with patch("arena.mobile.mirror.stats", return_value=[{"serial": "phone1"}]):
        resp = asyncio.run(handlers["mirror_stats"](req))
        assert resp.status == 200
        body = json.loads(resp.text)
        assert body == {"ok": True, "sessions": [{"serial": "phone1"}]}


def test_handle_mirror_stop_missing_and_existing():
    ctx = _MockContext()
    handlers = make_mirror_handlers(ctx, cors=_cors_response)

    # Missing session
    req_missing = make_mocked_request(
        "POST", "/v1/mobile/phone-none/mirror/stop",
        match_info={"serial": "phone-none"},
        headers={"Authorization": "Bearer t"},
    )
    resp_missing = asyncio.run(handlers["mirror_stop"](req_missing))
    assert resp_missing.status == 200
    body_missing = json.loads(resp_missing.text)
    assert body_missing["ok"] is False
    assert "no mirror session" in body_missing["error"]

    # Existing session
    session = MirrorSession(serial="phone-live", size=DEFAULT_SIZE, bit_rate=DEFAULT_BIT_RATE)
    with mirror._SESSIONS_LOCK:
        mirror._SESSIONS["phone-live"] = session

    req_live = make_mocked_request(
        "POST", "/v1/mobile/phone-live/mirror/stop",
        match_info={"serial": "phone-live"},
        headers={"Authorization": "Bearer t"},
    )
    resp_live = asyncio.run(handlers["mirror_stop"](req_live))
    assert resp_live.status == 200
    body_live = json.loads(resp_live.text)
    assert body_live == {"ok": True, "action": "mirror_stop", "serial": "phone-live"}
    assert session.stop_event.is_set()
    assert len(ctx.audit_events) == 1
    assert ctx.audit_events[0] == {"type": "mobile.mirror.stop", "serial": "phone-live"}


def test_handle_mirror_ws_validations():
    ctx = _MockContext()
    handlers = make_mirror_handlers(ctx, cors=_cors_response)

    # 1. Missing serial match_info
    req_no_serial = make_mocked_request("GET", "/v1/mobile//mirror/ws", headers={"Authorization": "Bearer t"})
    resp_no_serial = asyncio.run(handlers["mirror_ws"](req_no_serial))
    assert resp_no_serial.status == 400
    assert json.loads(resp_no_serial.text)["error"] == "serial required"

    # 2. ADB not found -> 503
    req_adb = make_mocked_request(
        "GET", "/v1/mobile/dev1/mirror/ws",
        match_info={"serial": "dev1"},
        headers={"Authorization": "Bearer t"},
    )
    with patch("arena.mobile.mirror.find_adb", return_value=None):
        resp_adb = asyncio.run(handlers["mirror_ws"](req_adb))
        assert resp_adb.status == 503
        assert json.loads(resp_adb.text)["error"] == "adb not installed"

    # 3. Invalid stream param -> 400
    req_bad_param = make_mocked_request(
        "GET", "/v1/mobile/dev1/mirror/ws?size=bad_size",
        match_info={"serial": "dev1"},
        headers={"Authorization": "Bearer t"},
    )
    with patch("arena.mobile.mirror.find_adb", return_value="/bin/adb"):
        resp_bad = asyncio.run(handlers["mirror_ws"](req_bad_param))
        assert resp_bad.status == 400
        assert "size must be WxH" in json.loads(resp_bad.text)["error"]


def test_handle_mirror_ws_full_flow():
    ctx = _MockContext()
    handlers = make_mirror_handlers(ctx, cors=_cors_response)

    req = make_mocked_request(
        "GET", "/v1/mobile/dev1/mirror/ws",
        match_info={"serial": "dev1"},
        headers={"Authorization": "Bearer t"},
    )

    class _MockWS:
        def __init__(self):
            self.closed = False
            self.sent_str = []
            self.sent_bytes = []
            self.done_event = asyncio.Event()

        async def prepare(self, req):
            return None

        async def send_str(self, s):
            self.sent_str.append(s)

        async def send_bytes(self, b):
            self.sent_bytes.append(b)
            self.done_event.set()

        def __aiter__(self):
            return self

        async def __anext__(self):
            # Wait until chunk is pumped
            await self.done_event.wait()
            self.closed = True
            msg = MagicMock()
            msg.type = WSMsgType.CLOSE
            return msg

    mock_ws = _MockWS()

    session = MirrorSession(serial="dev1", size=DEFAULT_SIZE, bit_rate=DEFAULT_BIT_RATE)

    with patch("arena.mobile.mirror.find_adb", return_value="/bin/adb"), \
         patch("aiohttp.web.WebSocketResponse", return_value=mock_ws), \
         patch("arena.mobile.mirror.get_or_start", return_value=session):

        async def _test():
            # In background, put _INIT_MARKER and a byte fragment into subscriber queue
            async def _feed():
                while not session.has_subscribers():
                    await asyncio.sleep(0.005)
                session.broadcast(_INIT_MARKER)
                session.broadcast(b"frame_bytes_001")

            feed_task = asyncio.create_task(_feed())
            ws_res = await handlers["mirror_ws"](req)
            await feed_task
            return ws_res

        res = asyncio.run(_test())
        assert res is mock_ws
        assert "__init__" in mock_ws.sent_str
        assert b"frame_bytes_001" in mock_ws.sent_bytes

        # Audit event recorded
        assert any(e.get("type") == "mobile.mirror.subscribe" and e.get("serial") == "dev1" for e in ctx.audit_events)
        # Session subscriber cleaned up and stop_event set
        assert not session.has_subscribers()
        assert session.stop_event.is_set()

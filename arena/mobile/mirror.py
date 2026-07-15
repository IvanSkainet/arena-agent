"""Live screen mirroring via H.264 → Python-native fragmented MP4 → WebSocket.

v3.84.6: replaced the ffmpeg-based muxer from v3.84.3 with an
in-process H.264 → fMP4 pipeline (`arena.mobile.mp4_muxer`). The old
pipeline BETA'd because ffmpeg's mp4 muxer buffered until keyframe
boundaries, and Android's AVC encoder can go 5+ s between IDRs on a
static home screen -- MediaSource timed out before the first fragment
ever landed. The new pipeline emits one moof+mdat per frame (VCL NAL),
so the browser paints on the very first P-frame after init.

Pipeline shape:

  1. `adb exec-out screenrecord --output-format=h264` streams raw NALs
     to the bridge process. One subprocess per phone serial.
  2. An asyncio reader task pumps bytes into `H264ToFMP4.feed()`.
  3. The muxer calls `on_init(bytes)` once (ftyp+moov) and
     `on_fragment(bytes, is_keyframe)` per frame (moof+mdat).
  4. Both callbacks fan out to every WebSocket subscriber via a
     per-session broadcast queue (dropping frames for slow consumers
     via the same asyncio.Queue(maxsize=32) backpressure as before).

`screenrecord` still hits its ~180 s hard limit per invocation; we
transparently spawn a fresh one and call `mux.reset()` so the next
SPS+PPS pair produces a new init segment.

Security posture unchanged from v3.84.3:
  * Bearer token (Authorization header or ?token= query) enforced in
    the WebSocket upgrade handshake.
  * One pipeline per serial; N subscribers share it.
  * Pipeline is a child of the bridge; SIGTERM tears it down.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from arena.mobile.adb import find_adb
from arena.mobile.mp4_muxer import H264ToFMP4

log = logging.getLogger(__name__)

DEFAULT_SIZE = "720x1600"
DEFAULT_BIT_RATE = 4_000_000
# Android AVC encoder hard-caps each screenrecord invocation at ~180 s.
# We restart at 170 s to keep a safety margin.
_SEGMENT_SECONDS = 170

# One MirrorSession per phone; N browser subscribers share it.
_SESSIONS: dict[str, "MirrorSession"] = {}
_SESSIONS_LOCK = threading.Lock()

# Special "control" marker delivered as its own broadcast. The
# WebSocket handler translates it to a text frame ("__init__") so the
# browser resets its MediaSource state.
_INIT_MARKER = b"__ARENA_INIT__"


@dataclass
class MirrorSession:
    serial: str
    size: str
    bit_rate: int
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    subscribers_lock: threading.Lock = field(default_factory=threading.Lock)
    reader_task: asyncio.Task | None = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    started_at: float = 0.0
    fragments_sent: int = 0
    bytes_sent: int = 0
    keyframes_sent: int = 0
    # v3.84.7: cache the last init segment and last keyframe fragment
    # so a subscriber that connects mid-stream can start decoding
    # immediately without waiting for the next screenrecord restart
    # (which is what got them a black `<video>` before this fix).
    last_init: bytes | None = None
    last_keyframe: bytes | None = None

    def add_subscriber(self) -> asyncio.Queue:
        """Register a new subscriber and pre-seed its queue with the
        cached init segment + last keyframe (if any). Without the
        seed, a subscriber that connects mid-stream would receive
        only P-frames until the next screenrecord restart, and
        MediaSource would show a black video element indefinitely."""
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        with self.subscribers_lock:
            self.subscribers.add(q)
        if self.last_init is not None:
            # A subscriber MUST see the init marker before it processes
            # the init segment bytes -- the client uses that marker to
            # (re)create the MediaSource SourceBuffer.
            try:
                q.put_nowait(_INIT_MARKER)
                q.put_nowait(self.last_init)
                if self.last_keyframe is not None:
                    q.put_nowait(self.last_keyframe)
            except asyncio.QueueFull:
                # Impossible on a fresh queue with maxsize=32, but
                # defensive.
                pass
        return q

    def remove_subscriber(self, q: asyncio.Queue) -> None:
        with self.subscribers_lock:
            self.subscribers.discard(q)

    def has_subscribers(self) -> bool:
        with self.subscribers_lock:
            return bool(self.subscribers)

    def broadcast(self, chunk: bytes) -> None:
        """Fan a chunk out to every subscriber. Slow consumers drop
        frames instead of stalling the pipeline for everyone."""
        with self.subscribers_lock:
            targets = list(self.subscribers)
        for q in targets:
            try:
                q.put_nowait(chunk)
            except asyncio.QueueFull:
                log.warning("mirror: subscriber queue full, dropping "
                            "%d bytes for %s", len(chunk), self.serial)
        # Update stats (not counting the control marker).
        if chunk != _INIT_MARKER:
            self.fragments_sent += 1
            self.bytes_sent += len(chunk)


def _screenrecord_cmd(serial: str, size: str, bit_rate: int) -> list[str]:
    return [
        find_adb() or "adb", "-s", serial,
        "exec-out", "screenrecord",
        "--output-format=h264",
        "--time-limit", str(_SEGMENT_SECONDS),
        "--size", size,
        "--bit-rate", str(bit_rate),
        "-",
    ]


async def _pump_pipeline(session: MirrorSession) -> None:
    """Run the screenrecord + Python muxer loop until the session ends.

    Restarts screenrecord when it exits (180 s AVC cap) or when it
    dies unexpectedly. Between restarts we call `mux.reset()` so the
    next SPS+PPS pair emits a fresh init segment; the browser's
    `__init__` marker prompts it to rebuild its MediaSource
    SourceBuffer.
    """
    import time
    session.started_at = time.time()
    log.info("mirror[%s]: pipeline started (python-native muxer)",
             session.serial)

    def _on_init(payload: bytes) -> None:
        # Cache the init segment so late-joining subscribers get it
        # too. Then tell current subscribers to reset their
        # SourceBuffer and hand them the freshly-built ftyp+moov.
        # We deliberately DROP any previously cached keyframe here --
        # it belonged to the old init and would fail to decode against
        # the new one (different SPS, different codec config).
        session.last_init = payload
        session.last_keyframe = None
        session.broadcast(_INIT_MARKER)
        session.broadcast(payload)

    def _on_fragment(payload: bytes, is_keyframe: bool) -> None:
        session.broadcast(payload)
        if is_keyframe:
            session.keyframes_sent += 1
            # Cache the latest keyframe so late-joining subscribers get
            # a decodable sync sample immediately.
            session.last_keyframe = payload

    mux = H264ToFMP4(on_init=_on_init, on_fragment=_on_fragment)

    try:
        while not session.stop_event.is_set() and session.has_subscribers():
            mux.reset()
            try:
                sr = await asyncio.create_subprocess_exec(
                    *_screenrecord_cmd(session.serial, session.size, session.bit_rate),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except Exception:
                log.exception("mirror[%s]: could not spawn screenrecord",
                              session.serial)
                await asyncio.sleep(1.0)
                continue

            async def _drain_sr_stderr():
                assert sr.stderr is not None
                while True:
                    line = await sr.stderr.readline()
                    if not line:
                        break
                    log.info("screenrecord: %s",
                             line.decode("utf-8", "replace").rstrip())
            stderr_task = asyncio.create_task(_drain_sr_stderr())

            try:
                assert sr.stdout is not None
                while True:
                    buf = await sr.stdout.read(65536)
                    if not buf:
                        break
                    mux.feed(buf)
                    if session.stop_event.is_set():
                        break
                    if not session.has_subscribers():
                        break
            finally:
                mux.flush()
                stderr_task.cancel()
                try:
                    sr.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(sr.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    try:
                        sr.kill()
                    except ProcessLookupError:
                        pass

            if session.stop_event.is_set() or not session.has_subscribers():
                break
            # Small pause between segment restarts.
            await asyncio.sleep(0.3)
    except Exception:
        log.exception("mirror[%s]: pipeline crashed", session.serial)
    finally:
        log.info("mirror[%s]: pipeline stopped after %d frags / %d bytes / %d keyframes",
                 session.serial,
                 session.fragments_sent, session.bytes_sent,
                 session.keyframes_sent)
        with _SESSIONS_LOCK:
            _SESSIONS.pop(session.serial, None)


def get_or_start(
    serial: str,
    *,
    size: str = DEFAULT_SIZE,
    bit_rate: int = DEFAULT_BIT_RATE,
    loop: asyncio.AbstractEventLoop | None = None,
) -> MirrorSession:
    """Return the mirror session for `serial`, spawning one if needed."""
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(serial)
        if session:
            return session
        session = MirrorSession(serial=serial, size=size, bit_rate=bit_rate)
        _SESSIONS[serial] = session
    loop = loop or asyncio.get_event_loop()
    session.reader_task = loop.create_task(_pump_pipeline(session))
    return session


def stop_all() -> None:
    """Torn down on bridge shutdown."""
    with _SESSIONS_LOCK:
        sessions = list(_SESSIONS.values())
    for s in sessions:
        s.stop_event.set()


def stats() -> list[dict[str, Any]]:
    """Snapshot for `GET /v1/mobile/mirror/stats`."""
    with _SESSIONS_LOCK:
        return [{
            "serial": s.serial,
            "size": s.size,
            "bit_rate": s.bit_rate,
            "started_at": s.started_at,
            "subscribers": len(s.subscribers),
            "fragments_sent": s.fragments_sent,
            "bytes_sent": s.bytes_sent,
            "keyframes_sent": s.keyframes_sent,
            "muxer": "python-native",
        } for s in _SESSIONS.values()]


# ---------------------------------------------------------------------------
# aiohttp handler -- WebSocket + stats/stop endpoints.
# ---------------------------------------------------------------------------

def make_mirror_handlers(ctx, *, cors):
    """Return the WS handler + stats/stop coroutines for /v1/mobile/*."""
    from aiohttp import WSMsgType, web

    async def handle_mirror_ws(request: web.Request) -> web.StreamResponse:
        r = ctx.require_auth(request)
        if r:
            return r
        serial = request.match_info.get("serial", "")
        if not serial:
            return cors({"ok": False, "error": "serial required"}, status=400)
        if find_adb() is None:
            return cors({"ok": False, "error": "adb not installed"}, status=503)

        size = request.query.get("size", DEFAULT_SIZE)
        try:
            bit_rate = int(request.query.get("bit_rate", DEFAULT_BIT_RATE))
        except ValueError:
            bit_rate = DEFAULT_BIT_RATE

        ws = web.WebSocketResponse(max_msg_size=0, autoping=True,
                                   heartbeat=15.0)
        await ws.prepare(request)

        session = get_or_start(serial, size=size, bit_rate=bit_rate)
        queue = session.add_subscriber()
        log.info("mirror[%s]: subscriber joined (%d total)",
                 serial, len(session.subscribers))
        ctx.audit({"type": "mobile.mirror.subscribe", "serial": serial})

        async def _pump():
            while not ws.closed:
                try:
                    chunk = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    continue
                if chunk == _INIT_MARKER:
                    try:
                        await ws.send_str("__init__")
                    except (ConnectionResetError, RuntimeError):
                        break
                    continue
                try:
                    await ws.send_bytes(chunk)
                except (ConnectionResetError, RuntimeError):
                    break

        pump_task = asyncio.create_task(_pump())
        try:
            async for msg in ws:
                if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR,
                                WSMsgType.CLOSED):
                    break
        finally:
            session.remove_subscriber(queue)
            pump_task.cancel()
            log.info("mirror[%s]: subscriber left (%d remain)",
                     serial, len(session.subscribers))
            if not session.has_subscribers():
                session.stop_event.set()
        return ws

    async def handle_mirror_stats(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        return cors({"ok": True, "sessions": stats()})

    async def handle_mirror_stop(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        serial = request.match_info.get("serial", "")
        with _SESSIONS_LOCK:
            s = _SESSIONS.get(serial)
        if not s:
            return cors({"ok": False, "error": f"no mirror session for {serial}"})
        s.stop_event.set()
        ctx.audit({"type": "mobile.mirror.stop", "serial": serial})
        return cors({"ok": True, "action": "mirror_stop", "serial": serial})

    return {
        "mirror_ws":    handle_mirror_ws,
        "mirror_stats": handle_mirror_stats,
        "mirror_stop":  handle_mirror_stop,
    }

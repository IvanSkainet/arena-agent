"""Live screen mirroring via H.264 → fragmented MP4 → WebSocket.

This is the "high FPS" answer to the Dashboard screenshot latency
problem the user has been asking about since v3.83.2. Instead of
capturing and encoding a full frame per HTTP request (which caps at
~0.4 fps even on the fast raw path), we:

  1. Start `adb exec-out screenrecord --output-format=h264` on the
     phone — Android's hardware AVC encoder streams raw NAL units
     to stdout at 25-30 fps.
  2. Pipe those NALs into a local `ffmpeg -c:v copy` that muxes them
     into a fragmented MP4 container (empty_moov + separate_moof +
     frag_keyframe flags). fMP4 is what MediaSource Extensions in
     modern browsers can play natively.
  3. Broadcast each fMP4 fragment to every connected WebSocket peer.
     The Dashboard side wraps them in a MediaSource + SourceBuffer
     and paints to a plain `<video>` element.

`screenrecord` still has its 180s hard limit per invocation, so we
transparently restart the pipeline when it exits. The Dashboard
gets an `init` chunk containing the fresh moov box on every restart
so MSE can re-initialise cleanly.

Security posture:
  * Same Bearer-token auth as every other /v1/mobile/* endpoint.
    Enforced in the WebSocket upgrade handshake.
  * Only ONE mirroring pipeline per (serial) at a time — a second
    connect returns the existing session.
  * Subprocess is a child of the bridge; on bridge stop / SIGTERM
    the pipeline is torn down (`terminate` then `kill` after 3s).
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any

from arena.mobile.adb import find_adb

log = logging.getLogger(__name__)

# Pipeline defaults. Bit-rate is deliberately modest — a 4 Mbps
# stream is essentially always small enough for a Tailscale tunnel
# and gives 720x1600 at 25fps room to breathe.
DEFAULT_SIZE = "720x1600"
DEFAULT_BIT_RATE = 4_000_000
# Each screenrecord invocation caps at this many seconds (Android AVC
# encoder hard-limit). We restart the pipeline before it hits the wall.
_SEGMENT_SECONDS = 170

# Registry keyed by serial. Two concurrent Dashboard tabs on the same
# device share one screenrecord + ffmpeg process; each tab is a
# separate subscriber getting the same fMP4 fragments.
_SESSIONS: dict[str, "MirrorSession"] = {}
_SESSIONS_LOCK = threading.Lock()


@dataclass
class MirrorSession:
    """One phone-side pipeline + N browser subscribers."""
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

    def add_subscriber(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        with self.subscribers_lock:
            self.subscribers.add(q)
        return q

    def remove_subscriber(self, q: asyncio.Queue) -> None:
        with self.subscribers_lock:
            self.subscribers.discard(q)

    def has_subscribers(self) -> bool:
        with self.subscribers_lock:
            return bool(self.subscribers)

    def broadcast(self, chunk: bytes) -> None:
        """Fan a fMP4 chunk out to every subscriber. Non-blocking:
        if a slow subscriber's queue is full we drop the frame for
        them rather than stalling the whole pipeline."""
        with self.subscribers_lock:
            targets = list(self.subscribers)
        for q in targets:
            try:
                q.put_nowait(chunk)
            except asyncio.QueueFull:
                # This subscriber is falling behind. Drop the frame
                # so the pipeline keeps up for everyone else.
                log.warning("mirror: subscriber queue full, dropping "
                            "%d bytes for %s", len(chunk), self.serial)
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


def _ffmpeg_cmd() -> list[str]:
    # `-c:v copy` = no re-encode, just remux. `-flush_packets 1` and
    # `-fflags nobuffer` push each NAL through as soon as it lands.
    # `empty_moov + separate_moof + default_base_moof + frag_keyframe`
    # is the flag combination MSE wants for a streaming fMP4.
    return [
        "ffmpeg",
        "-hide_banner", "-loglevel", "error",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-f", "h264", "-i", "-",
        "-c:v", "copy",
        "-movflags", "empty_moov+separate_moof+default_base_moof+frag_keyframe",
        "-f", "mp4",
        "-flush_packets", "1",
        "pipe:1",
    ]


async def _pump_pipeline(session: MirrorSession, loop: asyncio.AbstractEventLoop) -> None:
    """Runs the screenrecord | ffmpeg pipeline in a loop until the
    session is stopped. Restarts on segment expiry (~170s per
    Android's hard limit)."""
    import time
    session.started_at = time.time()
    log.info("mirror[%s]: pipeline started", session.serial)

    try:
        while not session.stop_event.is_set() and session.has_subscribers():
            # Spawn screenrecord (writing raw h264 to its stdout) and
            # ffmpeg (accepting h264 on stdin, muxing to fMP4). We
            # explicitly pump bytes from sr.stdout to ff.stdin from
            # Python — the earlier "os.pipe() shared fd" approach hung
            # ffmpeg because the two subprocesses each buffered
            # independently and neither saw an EOF until Python
            # forgot about them.
            sr = await asyncio.create_subprocess_exec(
                *_screenrecord_cmd(session.serial, session.size, session.bit_rate),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            ff = await asyncio.create_subprocess_exec(
                *_ffmpeg_cmd(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # Log ffmpeg stderr in the background so we see real errors.
            async def _drain_ff_stderr():
                while True:
                    line = await ff.stderr.readline()
                    if not line:
                        break
                    log.warning("ffmpeg: %s", line.decode("utf-8", "replace").rstrip())
            asyncio.create_task(_drain_ff_stderr())
            # Signal segment start (subscribers use this to reset the
            # MediaSource init state).
            session.broadcast(b"__ARENA_INIT__")

            async def _pump_h264():
                """Copy screenrecord stdout → ffmpeg stdin, close on EOF."""
                try:
                    while True:
                        buf = await sr.stdout.read(65536)
                        if not buf:
                            break
                        ff.stdin.write(buf)
                        try:
                            await ff.stdin.drain()
                        except (ConnectionResetError, BrokenPipeError):
                            break
                finally:
                    try:
                        ff.stdin.close()
                    except Exception:
                        pass

            pump = asyncio.create_task(_pump_h264())
            try:
                while True:
                    chunk = await ff.stdout.read(65536)
                    if not chunk:
                        break
                    session.broadcast(chunk)
                    if session.stop_event.is_set():
                        break
                    if not session.has_subscribers():
                        # Everyone left; shut down the pipeline until
                        # a new subscriber shows up.
                        break
            finally:
                pump.cancel()
                try:
                    await asyncio.wait_for(pump, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                for proc in (sr, ff):
                    try:
                        proc.terminate()
                    except ProcessLookupError:
                        pass
                # Give them 2s to die gracefully, then hard-kill.
                for proc in (sr, ff):
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                        except ProcessLookupError:
                            pass
            # Small pause so we don't hammer the phone if the pipeline
            # crashes repeatedly.
            if not session.has_subscribers() or session.stop_event.is_set():
                break
            await asyncio.sleep(0.3)
    except Exception:
        log.exception("mirror[%s]: pipeline crashed", session.serial)
    finally:
        log.info("mirror[%s]: pipeline stopped after %d frags / %d bytes",
                 session.serial, session.fragments_sent, session.bytes_sent)
        with _SESSIONS_LOCK:
            _SESSIONS.pop(session.serial, None)


def get_or_start(
    serial: str,
    *,
    size: str = DEFAULT_SIZE,
    bit_rate: int = DEFAULT_BIT_RATE,
    loop: asyncio.AbstractEventLoop | None = None,
) -> MirrorSession:
    """Return the mirror session for `serial`, spawning one if needed.

    Called from the WebSocket handler. A second call with different
    size/bit_rate is a no-op — the running session's settings win
    until every subscriber disconnects.
    """
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(serial)
        if session:
            return session
        session = MirrorSession(serial=serial, size=size, bit_rate=bit_rate)
        _SESSIONS[serial] = session
    loop = loop or asyncio.get_event_loop()
    session.reader_task = loop.create_task(_pump_pipeline(session, loop))
    return session


def stop_all() -> None:
    """Torn down on bridge shutdown."""
    with _SESSIONS_LOCK:
        sessions = list(_SESSIONS.values())
    for s in sessions:
        s.stop_event.set()


def stats() -> list[dict[str, Any]]:
    """Read-only snapshot for `GET /v1/mobile/{s}/mirror/stats`."""
    with _SESSIONS_LOCK:
        return [{
            "serial": s.serial,
            "size": s.size,
            "bit_rate": s.bit_rate,
            "started_at": s.started_at,
            "subscribers": len(s.subscribers),
            "fragments_sent": s.fragments_sent,
            "bytes_sent": s.bytes_sent,
        } for s in _SESSIONS.values()]


# ---------------------------------------------------------------------------
# aiohttp handler — the WebSocket endpoint
# ---------------------------------------------------------------------------

def make_mirror_handlers(ctx, *, cors):
    """Return the WS handler + stats/stop endpoints for /v1/mobile/*
    mirror routes. Kept in this module so the pipeline lifecycle
    stays in one file."""
    from aiohttp import WSMsgType, web

    async def handle_mirror_ws(request: web.Request) -> web.StreamResponse:
        # Bearer-token auth on WS upgrade. aiohttp doesn't apply the
        # normal middleware chain to raw upgrades, so we do it here.
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

        # Fan chunks from the pipeline into this WS.
        async def _pump():
            while not ws.closed:
                try:
                    chunk = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    continue
                if chunk == b"__ARENA_INIT__":
                    await ws.send_str("__init__")
                    continue
                try:
                    await ws.send_bytes(chunk)
                except (ConnectionResetError, RuntimeError):
                    break

        pump_task = asyncio.create_task(_pump())
        try:
            # Poll for client-side messages (currently only close /
            # ping; leave room for future control commands).
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

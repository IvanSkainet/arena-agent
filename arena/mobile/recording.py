"""Screen video recording via `adb shell screenrecord`.

`screenrecord` records the device display to an MP4 file on the phone.
The Arena bridge orchestrates it in two independent modes:

  * **Sync (short)** — `record_sync(serial, duration_ms=…)` blocks
    for the requested duration (capped at 180s by Android's own
    hard limit — the AVC encoder refuses longer). Returns the pulled
    MP4 bytes right in the response.

  * **Async (long)** — `start_async()` spawns screenrecord as a
    detached shell process (via `nohup` + `&`), stores the PID and
    output path in an in-memory registry, and returns immediately.
    `list_recordings()` reports every in-flight/finished recording,
    `stop_async(id)` sends SIGINT to the phone-side process to flush
    the container, and `pull_recording(id)` streams the resulting
    MP4 back.

Everything runs against the standard `/sdcard/DCIM/ArenaRecordings/`
directory so it doesn't clutter the user's Camera roll. Cleaned by
`purge_recordings()` (opt-in, called by CLI/UI only).
"""
from __future__ import annotations

import base64
import re
import threading
import time
import uuid
from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run

# `screenrecord` is capped at 180s per invocation by the Android AVC
# encoder — asking for more just makes the tool truncate at 180. We
# reject requests bigger than that up front so the caller gets a
# clear error instead of a silently-short video.
_MAX_DURATION_MS = 180_000
_MIN_DURATION_MS = 500
_MIN_BITRATE = 100_000        # 100 kbps
_MAX_BITRATE = 100_000_000    # 100 Mbps (headroom for 4K@60)

_RECORD_DIR = "/sdcard/DCIM/ArenaRecordings"

# Very loose validator so the caller can pass 720x1600 or 1920x1080
# without us second-guessing the encoder.
_SIZE_RE = re.compile(r"^(\d{2,5})x(\d{2,5})$")

# In-memory registry of async recordings. Bridge is single-process /
# multi-threaded so a module-level dict + lock is enough.
_REGISTRY: dict[str, dict[str, Any]] = {}
_REGISTRY_LOCK = threading.Lock()


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _ensure_adb() -> dict[str, Any] | None:
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}
    return None


def _validate_settings(duration_ms: int, size: str | None,
                       bit_rate: int) -> dict[str, Any] | None:
    if not isinstance(duration_ms, int):
        return _err("duration_ms must be an integer")
    if not (_MIN_DURATION_MS <= duration_ms <= _MAX_DURATION_MS):
        return _err(
            f"duration_ms out of range 500..180000: {duration_ms}",
            hint="Android's screenrecord tool caps a single call at 180s. "
                 "For longer sessions use the async API and stitch segments "
                 "on the client.",
        )
    if size is not None and not (isinstance(size, str) and _SIZE_RE.match(size)):
        return _err(f"size must be WxH (e.g. 720x1600), got {size!r}")
    if not isinstance(bit_rate, int) or not (_MIN_BITRATE <= bit_rate <= _MAX_BITRATE):
        return _err(f"bit_rate out of range {_MIN_BITRATE}..{_MAX_BITRATE}: {bit_rate}")
    return None


def _ensure_record_dir(serial: str) -> None:
    """Create /sdcard/DCIM/ArenaRecordings on demand. Ignores errors —
    if this fails, screenrecord itself will surface a friendlier one."""
    try:
        run(["shell", "mkdir", "-p", _RECORD_DIR], serial=serial, timeout=5)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Sync recording — blocks for `duration_ms`, then pulls the MP4 back.
# ---------------------------------------------------------------------------

def record_sync(
    serial: str,
    *,
    duration_ms: int = 5000,
    size: str | None = None,
    bit_rate: int = 4_000_000,
    include_bytes: bool = True,
    keep_on_device: bool = False,
) -> dict[str, Any]:
    """Record N ms of video, return the MP4 in the response.

    `size=None` = record at native display resolution (default).
    `include_bytes=False` skips the base64 payload and just returns
    metadata + the on-device path (use `pull_recording` to fetch later).
    """
    guard = _ensure_adb()
    if guard:
        return guard
    if not isinstance(serial, str) or not serial.strip():
        return _err("serial required")
    err = _validate_settings(duration_ms, size, bit_rate)
    if err:
        return err

    _ensure_record_dir(serial)
    remote = f"{_RECORD_DIR}/sync-{int(time.time())}-{uuid.uuid4().hex[:8]}.mp4"

    args = ["shell", "screenrecord",
            "--time-limit", str(max(1, duration_ms // 1000)),
            "--bit-rate", str(bit_rate)]
    if size:
        args += ["--size", size]
    args.append(remote)

    started = time.monotonic()
    try:
        r = run(args, serial=serial, timeout=(duration_ms // 1000) + 15)
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"screenrecord failed: {e}")
    record_ms = int((time.monotonic() - started) * 1000)

    if r.returncode != 0:
        stderr = (r.stderr or "").strip()
        return _err(stderr or f"screenrecord exit {r.returncode}",
                    exit_code=r.returncode, record_ms=record_ms)

    # Verify the file landed on the device.
    stat_rc, size_bytes = _stat_remote(serial, remote)
    if stat_rc != 0 or size_bytes == 0:
        return _err("recording did not land on device",
                    remote_path=remote, record_ms=record_ms)

    result: dict[str, Any] = {
        "ok": True,
        "action": "record_sync",
        "remote_path": remote,
        "size_bytes": size_bytes,
        "record_ms": record_ms,
        "requested_duration_ms": duration_ms,
        "settings": {
            "size": size, "bit_rate": bit_rate,
        },
    }
    if include_bytes:
        pulled = _pull_and_encode(serial, remote)
        if not pulled.get("ok"):
            return pulled
        result.update(pulled)
    if not keep_on_device:
        try:
            run(["shell", "rm", "-f", remote], serial=serial, timeout=10)
            result["cleaned_up"] = True
        except Exception:
            pass
    return result


def _stat_remote(serial: str, path: str) -> tuple[int, int]:
    try:
        r = run(["shell", "stat", "-c", "%s", path], serial=serial, timeout=5)
    except Exception:
        return (255, 0)
    if r.returncode != 0:
        return (r.returncode, 0)
    try:
        return (0, int((r.stdout or "0").strip()))
    except ValueError:
        return (255, 0)


def _pull_and_encode(serial: str, remote: str) -> dict[str, Any]:
    """Fetch a file via `adb exec-out cat` and return it base64-encoded."""
    try:
        r = run(["exec-out", "cat", remote], serial=serial,
                timeout=120, capture_binary=True)
    except AdbNotFoundError as e:
        return _err(str(e))
    if r.returncode != 0:
        return _err((r.stderr or b"").decode("utf-8", "replace").strip()
                    or f"cat exit {r.returncode}")
    data = r.stdout or b""
    if not data:
        return _err(f"remote file empty: {remote}")
    return {
        "ok": True,
        "mime": "video/mp4",
        "bytes_b64": base64.b64encode(data).decode("ascii"),
        "encoded_bytes": len(data),
    }


# ---------------------------------------------------------------------------
# Async recording — start, poll, stop, pull.
# ---------------------------------------------------------------------------

def start_async(
    serial: str,
    *,
    duration_ms: int = 30_000,
    size: str | None = None,
    bit_rate: int = 4_000_000,
) -> dict[str, Any]:
    """Kick off a detached screenrecord process on the phone.

    Returns `{ok, id, remote_path}` immediately; the recording runs on
    the phone for up to `duration_ms` (or until `stop_async` is called).
    """
    guard = _ensure_adb()
    if guard:
        return guard
    if not isinstance(serial, str) or not serial.strip():
        return _err("serial required")
    err = _validate_settings(duration_ms, size, bit_rate)
    if err:
        return err

    _ensure_record_dir(serial)
    rec_id = uuid.uuid4().hex[:12]
    remote = f"{_RECORD_DIR}/async-{int(time.time())}-{rec_id}.mp4"

    # Spawn a detached shell that runs screenrecord and writes its PID
    # to a sibling file. Using `sh -c '... &'` lets adb shell return
    # right away while the recorder keeps running.
    time_limit = max(1, duration_ms // 1000)
    size_flag = f" --size {size}" if size else ""
    inner = (
        f"screenrecord --time-limit {time_limit} "
        f"--bit-rate {bit_rate}{size_flag} {remote} "
        f"< /dev/null > /dev/null 2>&1 & "
        f"echo $! > {remote}.pid"
    )
    try:
        r = run(["shell", "sh", "-c", inner], serial=serial, timeout=10)
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"failed to spawn screenrecord: {e}")
    if r.returncode != 0:
        return _err((r.stderr or "").strip() or f"spawn exit {r.returncode}")

    # Read back the PID so we can kill it later.
    pid = None
    try:
        pid_r = run(["shell", "cat", f"{remote}.pid"], serial=serial, timeout=5)
        if pid_r.returncode == 0:
            pid_str = (pid_r.stdout or "").strip()
            if pid_str.isdigit():
                pid = int(pid_str)
    except Exception:
        pass

    entry = {
        "id": rec_id,
        "serial": serial,
        "remote_path": remote,
        "pid": pid,
        "started_at": time.time(),
        "settings": {"size": size, "bit_rate": bit_rate,
                     "duration_ms": duration_ms},
        "status": "running",
    }
    with _REGISTRY_LOCK:
        _REGISTRY[rec_id] = entry
    return {"ok": True, "action": "record_start", **entry}


def stop_async(rec_id: str) -> dict[str, Any]:
    """Signal the phone-side screenrecord to finish + finalise the MP4.

    screenrecord flushes the container on SIGINT / SIGTERM, so a plain
    `kill $pid` produces a valid file. `kill -9` corrupts it.
    """
    with _REGISTRY_LOCK:
        entry = _REGISTRY.get(rec_id)
        if not entry:
            return _err(f"unknown recording id: {rec_id}",
                        hint="Call GET /v1/mobile/{s}/recordings to list.")
        entry = dict(entry)  # copy for return

    serial = entry["serial"]
    pid = entry.get("pid")
    guard = _ensure_adb()
    if guard:
        return guard

    if pid:
        try:
            run(["shell", "kill", "-INT", str(pid)],
                serial=serial, timeout=5)
        except Exception:
            pass
    # Give screenrecord a moment to flush.
    time.sleep(0.6)

    with _REGISTRY_LOCK:
        e = _REGISTRY.get(rec_id)
        if e:
            e["status"] = "stopped"
            e["stopped_at"] = time.time()
    stat_rc, size_bytes = _stat_remote(serial, entry["remote_path"])
    return {
        "ok": True,
        "action": "record_stop",
        "id": rec_id,
        "remote_path": entry["remote_path"],
        "size_bytes": size_bytes if stat_rc == 0 else 0,
        "status": "stopped",
    }


def list_recordings(serial: str | None = None) -> dict[str, Any]:
    """Return the registry state. `serial=None` = all devices."""
    with _REGISTRY_LOCK:
        entries = [dict(e) for e in _REGISTRY.values()
                   if serial is None or e["serial"] == serial]
    # Refresh on-disk size for anything still tracked.
    guard = _ensure_adb()
    if guard is None:
        for e in entries:
            _rc, s = _stat_remote(e["serial"], e["remote_path"])
            e["current_size_bytes"] = s
    return {"ok": True, "count": len(entries), "recordings": entries}


def pull_recording(rec_id: str, *,
                   include_bytes: bool = True) -> dict[str, Any]:
    """Fetch a finished recording back to the caller."""
    with _REGISTRY_LOCK:
        entry = _REGISTRY.get(rec_id)
        if not entry:
            return _err(f"unknown recording id: {rec_id}")
        entry = dict(entry)
    serial = entry["serial"]
    guard = _ensure_adb()
    if guard:
        return guard
    stat_rc, size_bytes = _stat_remote(serial, entry["remote_path"])
    if stat_rc != 0 or size_bytes == 0:
        return _err("recording file missing or empty on device",
                    remote_path=entry["remote_path"],
                    hint="If the recording is still running, call "
                         "stop first.")
    result = {
        "ok": True,
        "id": rec_id,
        "remote_path": entry["remote_path"],
        "size_bytes": size_bytes,
        "status": entry.get("status", "unknown"),
    }
    if include_bytes:
        pulled = _pull_and_encode(serial, entry["remote_path"])
        if not pulled.get("ok"):
            return pulled
        result.update(pulled)
    return result


def purge_recordings(serial: str, *,
                     older_than_seconds: int = 0) -> dict[str, Any]:
    """Delete recordings from `_RECORD_DIR` and clear the registry.

    `older_than_seconds=0` (default) removes everything; a positive
    value keeps files younger than that threshold.
    """
    guard = _ensure_adb()
    if guard:
        return guard
    with _REGISTRY_LOCK:
        stale_ids = []
        cutoff = time.time() - older_than_seconds if older_than_seconds > 0 else None
        for rid, e in list(_REGISTRY.items()):
            if e["serial"] != serial:
                continue
            if cutoff is None or e["started_at"] < cutoff:
                stale_ids.append(rid)
        for rid in stale_ids:
            _REGISTRY.pop(rid, None)
    # And clean the directory itself.
    if older_than_seconds > 0:
        # find -mmin isn't available on Android's toybox; fall back to
        # deleting only what we know about via ls + stat.
        try:
            run(["shell", "sh", "-c",
                 f"for f in {_RECORD_DIR}/*.mp4; do "
                 f"  age=$(( $(date +%s) - $(stat -c %Y \"$f\" 2>/dev/null || echo 0) )); "
                 f"  [ \"$age\" -gt {older_than_seconds} ] && rm -f \"$f\"; "
                 f"done"],
                serial=serial, timeout=20)
        except Exception:
            pass
    else:
        try:
            run(["shell", "sh", "-c", f"rm -f {_RECORD_DIR}/*.mp4 {_RECORD_DIR}/*.pid"],
                serial=serial, timeout=10)
        except Exception:
            pass
    return {"ok": True, "action": "purge",
            "cleared_ids": stale_ids,
            "kept_older_than_seconds": older_than_seconds}

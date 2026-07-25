"""First-class microphone capture for the bridge ("hearing"), v4.84.0.

A tiny bridge-bundled Android app (``assets/apks/arena-voicerecorder.apk``,
package ``com.arena.voicerecorder``) records from ``AudioSource.MIC`` into
an AAC-in-MP4 file on the device. This module is the bridge side:

  1. ``ensure_installed`` — install the bundled APK once (idempotent;
     checked via ``pm path``).
  2. ``ensure_permissions`` — ``pm grant RECORD_AUDIO`` + ``appops set
     MANAGE_EXTERNAL_STORAGE allow`` so the app can write the recording
     into ``/sdcard/DCIM/ArenaRecordings/`` (the same dir the bridge's
     screen recordings use, which adb can pull back).
  3. ``voice_record`` — ``am start`` the recorder with a duration + output
     path, poll the ``<output>.done`` marker the app writes on completion,
     pull the MP4 back to the host and report status.

Capture is fully under bridge control — the system Recorder app is NOT
driven — so this is app-independent and durable. Transcription is a
separate ``asr.transcribe`` call on the returned path (the agent composes
the two general capabilities).

The pure helpers (``pm_path_installed``, ``parse_done_marker``,
``default_output_path``, ``bundled_apk_path``) are unit-testable without a
device; the adb orchestration is exercised live.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from arena.mobile.adb import find_adb, run

PKG = "com.arena.voicerecorder"
ACTIVITY = ".ArenaVoiceRecorder"
APK_NAME = "arena-voicerecorder.apk"
RECORD_DIR = "/sdcard/DCIM/ArenaRecordings"
_DEVICE_TMP_APK = "/data/local/tmp/arena-voicerecorder.apk"
_DONE_TIMEOUT_BUFFER_S = 15
_POLL_INTERVAL_S = 0.5


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _ensure_adb() -> dict[str, Any] | None:
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}
    return None


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable, no device required)
# ---------------------------------------------------------------------------

def bundled_apk_path() -> Path:
    """Absolute path to the bundled recorder APK shipped with the bridge."""
    return Path(__file__).resolve().parents[2] / "assets" / "apks" / APK_NAME


def default_output_path(epoch_ms: int | None = None) -> str:
    """On-device MP4 path for a new capture (in the bridge's record dir)."""
    ts = epoch_ms if epoch_ms is not None else int(time.time() * 1000)
    return f"{RECORD_DIR}/voice-{ts}.m4a"


def pm_path_installed(pm_path_stdout: str) -> bool:
    """True when ``pm path <pkg>`` output indicates the package is present.

    Installed: ``package:/data/app/...``. Not installed: empty output (and
    a non-zero exit, which the caller checks separately)."""
    return "package:" in (pm_path_stdout or "")


def parse_done_marker(content: str) -> tuple[bool, str]:
    """Parse the recorder app's ``<output>.done`` marker.

    The app writes ``ok`` on success or ``error:<reason>`` on failure.
    Returns ``(ok, detail)`` — ``detail`` is ``""`` on success or the
    reason string on failure. Unknown/empty content is treated as a
    failure so the caller never mistakes a partial write for success."""
    text = (content or "").strip()
    if text == "ok":
        return True, ""
    if text.startswith("error:"):
        return False, text[len("error:"):]
    return False, text or "unknown-marker"


def voice_capture_dir() -> Path:
    """Host directory pulled voice captures land in (0700)."""
    root = Path(os.environ.get("ARENA_VOICE_DIR")
                or (Path.home() / ".arena" / "voice-captures")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


# ---------------------------------------------------------------------------
# adb orchestration
# ---------------------------------------------------------------------------

def ensure_installed(serial: str, *, force: bool = False) -> dict[str, Any]:
    """Install the bundled recorder APK if not already present.

    Idempotent: skips the install when ``pm path`` reports the package.
    ``force=True`` reinstalls (``pm install -r``) regardless."""
    guard = _ensure_adb()
    if guard:
        return guard
    apk = bundled_apk_path()
    if not apk.is_file():
        return _err(f"bundled recorder APK missing: {apk}",
                    hint="reinstall/refresh the bridge package")

    if not force:
        r = run(["shell", "pm", "path", PKG], serial=serial, timeout=15)
        if r.returncode == 0 and pm_path_installed(r.stdout or ""):
            return {"ok": True, "installed": False, "package": PKG}

    push = run(["push", str(apk), _DEVICE_TMP_APK], serial=serial, timeout=120)
    if push.returncode != 0:
        return _err("adb push of recorder APK failed",
                    detail=(push.stderr or push.stdout or "").strip()[-400:])
    inst = run(["shell", "pm", "install", "-r", _DEVICE_TMP_APK],
               serial=serial, timeout=120)
    out = (inst.stdout or "").strip()
    try:
        run(["shell", "rm", "-f", _DEVICE_TMP_APK], serial=serial, timeout=10)
    except Exception:
        pass
    if inst.returncode != 0 or "Success" not in out:
        return _err("pm install of recorder APK failed",
                    detail=(out or inst.stderr or "").strip()[-400:])
    return {"ok": True, "installed": True, "package": PKG}


def ensure_permissions(serial: str) -> dict[str, Any]:
    """Grant RECORD_AUDIO and MANAGE_EXTERNAL_STORAGE to the recorder app."""
    guard = _ensure_adb()
    if guard:
        return guard
    granted = {}
    r = run(["shell", "pm", "grant", PKG, "android.permission.RECORD_AUDIO"],
            serial=serial, timeout=15)
    granted["record_audio"] = r.returncode == 0
    r = run(["shell", "appops", "set", PKG, "MANAGE_EXTERNAL_STORAGE", "allow"],
            serial=serial, timeout=15)
    granted["manage_external_storage"] = r.returncode == 0
    if not granted["record_audio"]:
        return _err("could not grant RECORD_AUDIO", granted=granted)
    return {"ok": True, "granted": granted}


def _read_done(serial: str, marker: str) -> str | None:
    """Return the done-marker content, or None if it doesn't exist yet."""
    try:
        r = run(["shell", "cat", marker], serial=serial, timeout=5)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout or ""


def voice_record(
    serial: str,
    *,
    duration_ms: int = 8000,
    return_bytes: bool = False,
    keep_on_device: bool = False,
    install_timeout_s: int = 180,
) -> dict[str, Any]:
    """Capture `duration_ms` of microphone audio, pull it back to the host.

    Returns ``{ok, remote, local, size_bytes, status, detail, record_ms}``
    (plus ``bytes_b64`` when ``return_bytes``). ``status`` mirrors the
    recorder app's done marker (``ok`` / the error reason)."""
    guard = _ensure_adb()
    if guard:
        return guard
    if not isinstance(serial, str) or not serial.strip():
        return _err("serial required")
    if not isinstance(duration_ms, int) or not (500 <= duration_ms <= 600_000):
        return _err(f"duration_ms out of range 500..600000: {duration_ms}")

    inst = ensure_installed(serial)
    if not inst.get("ok"):
        return inst
    perm = ensure_permissions(serial)
    if not perm.get("ok"):
        return perm

    output = default_output_path()
    marker = output + ".done"
    # Clear any stale marker so we don't read a previous run's result.
    try:
        run(["shell", "rm", "-f", marker], serial=serial, timeout=5)
    except Exception:
        pass

    started = time.monotonic()
    start = run(
        ["shell", "am", "start", "-n", f"{PKG}/{ACTIVITY}",
         "--ei", "duration_ms", str(duration_ms),
         "--es", "output", output],
        serial=serial, timeout=20)
    if start.returncode != 0 or "Error" in (start.stdout or ""):
        return _err("am start of recorder failed",
                    detail=(start.stdout or start.stderr or "").strip()[-400:])

    # Poll the done marker until the app signals completion or we time out.
    deadline = started + (duration_ms / 1000.0) + _DONE_TIMEOUT_BUFFER_S
    content: str | None = None
    while time.monotonic() < deadline:
        content = _read_done(serial, marker)
        if content is not None:
            break
        time.sleep(_POLL_INTERVAL_S)

    if content is None:
        return _err("recording did not signal completion in time",
                    remote=output,
                    hint="the recorder app may have been blocked in the "
                         "background; retry or increase the buffer")

    ok, detail = parse_done_marker(content)
    record_ms = int((time.monotonic() - started) * 1000)
    if not ok:
        return _err(f"recorder reported failure: {detail}",
                    remote=output, status=detail, record_ms=record_ms)

    # Pull the MP4 back to the host voice-capture dir.
    local = str(voice_capture_dir() / Path(output).name)
    pull = run(["pull", output, local], serial=serial, timeout=120)
    if pull.returncode != 0 or not Path(local).is_file():
        return _err("adb pull of recording failed",
                    remote=output,
                    detail=(pull.stderr or pull.stdout or "").strip()[-400:])
    size_bytes = Path(local).stat().st_size
    if size_bytes == 0:
        return _err("pulled recording is empty", remote=output, local=local)

    result: dict[str, Any] = {
        "ok": True,
        "remote": output,
        "local": local,
        "size_bytes": size_bytes,
        "status": "ok",
        "record_ms": record_ms,
        "mime": "audio/mp4",
        "package": PKG,
    }
    if return_bytes:
        import base64
        result["bytes_b64"] = base64.b64encode(Path(local).read_bytes()).decode("ascii")
    if not keep_on_device:
        try:
            run(["shell", "rm", "-f", output, marker], serial=serial, timeout=10)
            result["cleaned_up"] = True
        except Exception:
            pass
    return result

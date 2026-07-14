"""Input automation via `adb shell input ...`.

Provides tap/swipe/type/key primitives that mirror the desktop input
handler's contract as closely as Android permits. All validation happens
here — the aiohttp handler stays a thin translation layer.
"""
from __future__ import annotations

from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run

# `adb shell input keyevent` accepts either an integer keycode or the
# textual name. The list is deliberately conservative — enough for
# navigation and text entry, without exposing rebooting or power-off.
_ALLOWED_KEYS: frozenset[str] = frozenset({
    # Navigation / system
    "HOME", "BACK", "MENU", "APP_SWITCH", "RECENTS",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "DPAD_CENTER",
    "TAB", "ENTER", "ESCAPE", "SPACE",
    # Text editing
    "DEL", "FORWARD_DEL", "MOVE_HOME", "MOVE_END",
    # Media / volume (harmless & useful)
    "VOLUME_UP", "VOLUME_DOWN", "VOLUME_MUTE",
    "MEDIA_PLAY", "MEDIA_PAUSE", "MEDIA_PLAY_PAUSE", "MEDIA_NEXT", "MEDIA_PREVIOUS",
    # Screen
    "WAKEUP", "SLEEP",
    # Common letters/numbers can be sent via `input text` instead — we
    # deliberately do not allow raw letter keycodes because agents that
    # want to "type" should call the type endpoint (which is unicode-safe).
})


def _err(msg: str) -> dict[str, Any]:
    return {"ok": False, "error": msg}


def _ensure_adb() -> dict[str, Any] | None:
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}
    return None


def tap(serial: str, x: int, y: int) -> dict[str, Any]:
    """Single-tap at (x, y). Coordinates are display pixels."""
    guard = _ensure_adb()
    if guard:
        return guard
    if not isinstance(x, int) or not isinstance(y, int):
        return _err("x and y must be integers")
    if x < 0 or y < 0 or x > 100000 or y > 100000:
        return _err(f"tap coordinates out of range: ({x}, {y})")
    try:
        r = run(["shell", "input", "tap", str(x), str(y)], serial=serial, timeout=10)
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"tap failed: {e}")
    ok = r.returncode == 0
    return {
        "ok": ok,
        "action": "tap",
        "x": x, "y": y,
        "stdout": r.stdout, "stderr": r.stderr,
        "exit_code": r.returncode,
        "error": None if ok else (r.stderr or f"input tap exit {r.returncode}").strip(),
    }


def swipe(
    serial: str,
    x1: int, y1: int, x2: int, y2: int,
    duration_ms: int = 300,
) -> dict[str, Any]:
    """Swipe / drag from (x1,y1) to (x2,y2) over `duration_ms`."""
    guard = _ensure_adb()
    if guard:
        return guard
    for name, val in (("x1", x1), ("y1", y1), ("x2", x2), ("y2", y2), ("duration_ms", duration_ms)):
        if not isinstance(val, int):
            return _err(f"{name} must be an integer")
    if duration_ms < 1 or duration_ms > 60_000:
        return _err(f"duration_ms out of range: {duration_ms}")
    try:
        r = run(
            ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            serial=serial, timeout=max(10, duration_ms // 1000 + 5),
        )
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"swipe failed: {e}")
    ok = r.returncode == 0
    return {
        "ok": ok,
        "action": "swipe",
        "from": [x1, y1], "to": [x2, y2],
        "duration_ms": duration_ms,
        "stdout": r.stdout, "stderr": r.stderr,
        "exit_code": r.returncode,
        "error": None if ok else (r.stderr or f"input swipe exit {r.returncode}").strip(),
    }


def type_text(serial: str, text: str) -> dict[str, Any]:
    """Type unicode text through `adb shell input text`.

    `adb shell input text` is limited to ASCII on many Android builds —
    non-ASCII input may drop characters silently. For richer input the
    caller should use IME-based methods (out of scope for Phase 1).
    """
    guard = _ensure_adb()
    if guard:
        return guard
    if not isinstance(text, str):
        return _err("text must be a string")
    if len(text) > 4096:
        return _err(f"text too long ({len(text)} chars; max 4096)")

    # `input text` treats spaces as separators — %s is the documented escape.
    safe = text.replace("\\", "\\\\").replace(" ", "%s").replace("'", "\\'")
    try:
        r = run(["shell", "input", "text", safe], serial=serial, timeout=15)
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"type failed: {e}")
    ok = r.returncode == 0
    return {
        "ok": ok,
        "action": "type",
        "chars": len(text),
        "stdout": r.stdout, "stderr": r.stderr,
        "exit_code": r.returncode,
        "error": None if ok else (r.stderr or f"input text exit {r.returncode}").strip(),
    }


def key(serial: str, key_name: str) -> dict[str, Any]:
    """Send an Android key event via allowlist.

    `key_name` is the symbolic KEYCODE name without the `KEYCODE_` prefix
    (e.g. `HOME`, `BACK`, `VOLUME_UP`). Only keys in the allowlist are
    accepted so an agent cannot pass e.g. `POWER` to force a reboot.
    """
    guard = _ensure_adb()
    if guard:
        return guard
    if not isinstance(key_name, str):
        return _err("key must be a string")
    upper = key_name.upper().replace("KEYCODE_", "").strip()
    if upper not in _ALLOWED_KEYS:
        return _err(
            f"key {key_name!r} is not on the allowlist. "
            f"Allowed: {sorted(_ALLOWED_KEYS)}"
        )
    try:
        r = run(["shell", "input", "keyevent", f"KEYCODE_{upper}"], serial=serial, timeout=10)
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"key event failed: {e}")
    ok = r.returncode == 0
    return {
        "ok": ok,
        "action": "key",
        "key": upper,
        "stdout": r.stdout, "stderr": r.stderr,
        "exit_code": r.returncode,
        "error": None if ok else (r.stderr or f"input keyevent exit {r.returncode}").strip(),
    }

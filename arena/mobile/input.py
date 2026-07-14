"""Input automation via `adb shell input ...`.

Provides tap/swipe/type/key primitives that mirror the desktop input
handler's contract as closely as Android permits. All validation happens
here — the aiohttp handler stays a thin translation layer.

Notes on `input text` reliability (v3.82.2):
  * On Android 15/16 (HyperOS/POCO F7 Pro was our reference device)
    Google's stock IME (LatinIME) refuses non-ASCII payloads and the
    input service raises a bare `NullPointerException: Attempt to get
    length of null array` deep in `InputShellCommand.sendText`. That
    is not something we can recover from at the shell layer, so we
    reject non-ASCII **before** ever invoking adb and return an actionable
    hint. Unicode input via ADBKeyboard helper is planned for Mobile
    Phase 2 (v3.83.0).
  * Empty / whitespace-only text triggers the same NPE (Android tries
    to tokenise the escaped string and hits null), so we reject that up
    front too.
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


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _ensure_adb() -> dict[str, Any] | None:
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}
    return None


def tap(serial: str, x: int, y: int) -> dict[str, Any]:
    """Single-tap at (x, y). Coordinates are display pixels."""
    # Validate arguments BEFORE the adb-present check so callers get a
    # deterministic parameter error even on hosts without adb (matters
    # for CI, and also matches the security posture — bad inputs are
    # rejected identically regardless of runtime state).
    if not isinstance(x, int) or not isinstance(y, int):
        return _err("x and y must be integers")
    if x < 0 or y < 0 or x > 100000 or y > 100000:
        return _err(f"tap coordinates out of range: ({x}, {y})")
    guard = _ensure_adb()
    if guard:
        return guard
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
    for name, val in (("x1", x1), ("y1", y1), ("x2", x2), ("y2", y2), ("duration_ms", duration_ms)):
        if not isinstance(val, int):
            return _err(f"{name} must be an integer")
    if duration_ms < 1 or duration_ms > 60_000:
        return _err(f"duration_ms out of range: {duration_ms}")
    guard = _ensure_adb()
    if guard:
        return guard
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


# ---------------------------------------------------------------------------
# type_text — with strict up-front validation
# ---------------------------------------------------------------------------

# Documented in the module docstring: the underlying Android command is
# fragile with non-ASCII payloads on modern IMEs (LatinIME on Android 15+
# raises a bare NPE). We reject those inputs at the API boundary so we
# never surface a Java stack trace to the user.
_NON_ASCII_HINT = (
    "adb's `input text` cannot encode non-ASCII characters on this device's "
    "IME (LatinIME / HyperOS return an internal NullPointerException). "
    "Non-ASCII input is planned for Mobile Phase 2 via the ADBKeyboard "
    "helper. For now, either strip the input to ASCII, or paste the text "
    "manually into the phone."
)
_EMPTY_HINT = (
    "`input text` requires at least one non-whitespace character; on "
    "modern Android it crashes with a NullPointerException when the "
    "payload is empty or whitespace-only."
)


def type_text(serial: str, text: str) -> dict[str, Any]:
    """Type ASCII text through `adb shell input text`.

    Non-ASCII and empty/whitespace-only payloads are rejected up front —
    on modern Android (15/16) the input service crashes with a bare
    NullPointerException in both cases and there is no way to distinguish
    the failure from a legitimate one at the shell layer.
    """
    if not isinstance(text, str):
        return _err("text must be a string")
    if len(text) > 4096:
        return _err(f"text too long ({len(text)} chars; max 4096)")

    stripped = text.strip()
    if not stripped:
        return _err(
            "text is empty or whitespace-only",
            hint=_EMPTY_HINT,
            action="type",
        )

    # Non-ASCII pre-flight — LatinIME can't encode this and Android <=16
    # returns a bare NPE we can't do anything useful with.
    non_ascii = [c for c in text if ord(c) > 127]
    if non_ascii:
        # Show up to 8 offending characters + their code points so the
        # user knows what to strip.
        sample = "".join(non_ascii[:8])
        codepoints = ", ".join(f"U+{ord(c):04X}" for c in non_ascii[:8])
        more = "" if len(non_ascii) <= 8 else f" (+{len(non_ascii) - 8} more)"
        return _err(
            f"text contains {len(non_ascii)} non-ASCII character(s): {sample!r}{more}",
            hint=_NON_ASCII_HINT,
            offending_codepoints=codepoints,
            action="type",
        )

    guard = _ensure_adb()
    if guard:
        return guard

    # `input text` treats spaces as separators — %s is the documented escape.
    safe = text.replace("\\", "\\\\").replace(" ", "%s").replace("'", "\\'")
    try:
        r = run(["shell", "input", "text", safe], serial=serial, timeout=15)
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"type failed: {e}")
    ok = r.returncode == 0
    err_msg = None
    if not ok:
        raw = (r.stderr or r.stdout or f"input text exit {r.returncode}").strip()
        err_msg = _friendly_type_error(raw)
    return {
        "ok": ok,
        "action": "type",
        "chars": len(text),
        "stdout": r.stdout, "stderr": r.stderr,
        "exit_code": r.returncode,
        "error": err_msg,
    }


def _friendly_type_error(raw: str) -> str:
    """Rewrite the most common `adb shell input text` failures into a
    hint that a human can act on. Preserves the raw text so nothing is
    hidden.
    """
    lower = raw.lower()
    if "no focused window" in lower or "no window focus" in lower:
        return (
            "No focused text field on the device. Tap into an input "
            "field first (e.g. the address bar or a search box), "
            "then try typing again. Original error: " + raw
        )
    if "input service does not have permission" in lower or "securityexception" in lower:
        return (
            "Android refused the input event (likely a permission or "
            "IME issue). On Xiaomi/HyperOS make sure USB debugging "
            "(Security settings) is enabled in Developer Options. "
            "Original error: " + raw
        )
    if "nullpointerexception" in lower and "length of null array" in lower:
        # We already pre-filter non-ASCII and empty payloads, so if we
        # still see this it means the current IME just refused the event
        # (e.g. no focused editor, or the IME is a stub like GBoard's
        # voice input).
        return (
            "Android's input service returned a NullPointerException — "
            "the currently focused IME rejected the payload. Tap an "
            "editable text field first, or switch the default IME to a "
            "standard keyboard. Original error: " + raw
        )
    if "illegalargumentexception" in lower and "keyevent" in lower:
        return (
            "The text contains characters that adb's `input text` cannot "
            "encode on this device's IME. Try ASCII-only text, or paste "
            "via clipboard. Original error: " + raw
        )
    return raw


def key(serial: str, key_name: str) -> dict[str, Any]:
    """Send an Android key event via allowlist.

    `key_name` is the symbolic KEYCODE name without the `KEYCODE_` prefix
    (e.g. `HOME`, `BACK`, `VOLUME_UP`). Only keys in the allowlist are
    accepted so an agent cannot pass e.g. `POWER` to force a reboot.
    """
    if not isinstance(key_name, str):
        return _err("key must be a string")
    upper = key_name.upper().replace("KEYCODE_", "").strip()
    if upper not in _ALLOWED_KEYS:
        return _err(
            f"key {key_name!r} is not on the allowlist. "
            f"Allowed: {sorted(_ALLOWED_KEYS)}"
        )
    guard = _ensure_adb()
    if guard:
        return guard
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

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

import re
from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run

# `adb shell input keyevent` accepts either an integer keycode or the
# textual name. Kept conservative — enough for navigation, text entry
# and a physical-keyboard-like experience from the Dashboard, without
# exposing rebooting or power-off.
_ALLOWED_KEYS: frozenset[str] = frozenset({
    # Navigation / system
    "HOME", "BACK", "MENU", "APP_SWITCH", "RECENTS", "NOTIFICATION",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "DPAD_CENTER",
    "TAB", "ENTER", "ESCAPE", "SPACE",
    # Text editing
    "DEL", "FORWARD_DEL", "MOVE_HOME", "MOVE_END",
    "PAGE_UP", "PAGE_DOWN",
    # Media / volume
    "VOLUME_UP", "VOLUME_DOWN", "VOLUME_MUTE",
    "MEDIA_PLAY", "MEDIA_PAUSE", "MEDIA_PLAY_PAUSE", "MEDIA_NEXT", "MEDIA_PREVIOUS",
    # Screen
    "WAKEUP", "SLEEP",
    # Modifier / meta keys — useful for keyboard forwarding + key_combo
    "SHIFT_LEFT", "SHIFT_RIGHT", "CTRL_LEFT", "CTRL_RIGHT",
    "ALT_LEFT", "ALT_RIGHT", "META_LEFT", "META_RIGHT",
    "CAPS_LOCK", "NUM_LOCK", "SCROLL_LOCK",
    # Editor shortcuts as first-class keys (Android maps Ctrl+C etc, but
    # some apps only listen for these direct codes).
    "COPY", "PASTE", "CUT", "SELECT_ALL", "UNDO", "REDO", "SEARCH",
    "ZOOM_IN", "ZOOM_OUT",
    # Function keys
    "F1", "F2", "F3", "F4", "F5", "F6",
    "F7", "F8", "F9", "F10", "F11", "F12",
})
# Letters A-Z and digits 0-9 are allowed as-is so the Dashboard can
# forward a physical-keyboard press through `key`. They aren't in the
# frozenset above because adding 36 more entries would drown out the
# semantic keys in error messages — instead we check the pattern.
_LETTER_OR_DIGIT_RE = re.compile(r"^(?:[A-Z]|[0-9])$")

# `input keycombination` (Android 12+) accepts two or more keycodes to
# press together, e.g. Ctrl+A. Guarded by the same allowlist as `key`.
_MAX_COMBO_KEYS = 4


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
    "adb's built-in `input text` cannot encode non-ASCII characters "
    "on stock IMEs (LatinIME on Android 15/16 returns a bare "
    "NullPointerException). Install the ADBKeyboard helper (POST "
    "/v1/mobile/{serial}/helpers/install) and activate it (POST "
    "/v1/mobile/{serial}/helpers/ime_set) — then `type_text` will "
    "auto-route non-ASCII through ADBKeyboard's ADB_INPUT_B64 broadcast."
)
_EMPTY_HINT = (
    "`input text` requires at least one non-whitespace character; on "
    "modern Android it crashes with a NullPointerException when the "
    "payload is empty or whitespace-only."
)


def type_text(serial: str, text: str) -> dict[str, Any]:
    """Type text through the most appropriate channel.

    ASCII payloads go through `adb shell input text` (fast, no helper
    needed). Non-ASCII payloads auto-route through ADBKeyboard's
    ADB_INPUT_B64 broadcast — but only if ADBKeyboard is already the
    active IME on the device. If it isn't, we return an actionable
    error telling the caller how to install and activate it, instead
    of silently sending unicode into Android's crash-prone builtin.
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

    # Non-ASCII path — route through ADBKeyboard when available.
    non_ascii = [c for c in text if ord(c) > 127]
    if non_ascii:
        # Lazy import to keep the module load order clean; helpers imports
        # from input.py indirectly for shared error shapes.
        from arena.mobile import helpers as _helpers
        status = _helpers.ime_status(serial)
        if status.get("ok") and status.get("adbkeyboard_active"):
            # Route through ADBKeyboard. Same envelope as the ASCII path
            # so the Dashboard doesn't need a special case: `action` is
            # normalised to "type" (the user asked to type), `route`
            # tells the audit trail which backend actually delivered it.
            paste = _helpers.paste_text(serial, text)
            paste = dict(paste)
            paste["action"] = "type"
            paste["route"] = "adbkeyboard"
            paste["chars"] = len(text)
            return paste
        # ADBKeyboard not active — fall through with an actionable error.
        sample = "".join(non_ascii[:8])
        codepoints = ", ".join(f"U+{ord(c):04X}" for c in non_ascii[:8])
        more = "" if len(non_ascii) <= 8 else f" (+{len(non_ascii) - 8} more)"
        extras: dict[str, Any] = {
            "offending_codepoints": codepoints,
            "action": "type",
            "route": "blocked",
        }
        if status.get("ok"):
            extras["adbkeyboard_installed"] = status.get("adbkeyboard_installed", False)
            extras["adbkeyboard_active"] = status.get("adbkeyboard_active", False)
            extras["current_ime"] = status.get("current")
        return _err(
            f"text contains {len(non_ascii)} non-ASCII character(s): {sample!r}{more}",
            hint=_NON_ASCII_HINT,
            **extras,
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


def _normalise_key(key_name: Any) -> tuple[str | None, str | None]:
    """Return (upper, error) — upper is the accepted `KEYCODE_<X>` tail,
    or None if `key_name` is invalid / not on the allowlist. Letters A-Z
    and digits 0-9 are accepted without being enumerated in the frozenset
    so error messages stay short."""
    if not isinstance(key_name, str):
        return None, "key must be a string"
    upper = key_name.upper().replace("KEYCODE_", "").strip()
    if not upper:
        return None, "key must not be empty"
    if upper in _ALLOWED_KEYS:
        return upper, None
    if _LETTER_OR_DIGIT_RE.match(upper):
        return upper, None
    return None, (
        f"key {key_name!r} is not on the allowlist. "
        f"Named keys: {sorted(_ALLOWED_KEYS)}; also A-Z and 0-9 are accepted."
    )


def key(serial: str, key_name: str) -> dict[str, Any]:
    """Send an Android key event via allowlist.

    `key_name` is the symbolic KEYCODE name without the `KEYCODE_` prefix
    (e.g. `HOME`, `BACK`, `VOLUME_UP`, `A`, `7`). Only allowlisted keys
    or single letters/digits are accepted so an agent cannot pass e.g.
    `POWER` to force a reboot.
    """
    upper, err = _normalise_key(key_name)
    if err:
        return _err(err)
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


def key_combo(serial: str, keys: list[str]) -> dict[str, Any]:
    """Press a combination of keys together (e.g. Ctrl+A → SELECT_ALL).

    Uses `adb shell input keycombination` which fires all keys down,
    then all keys up — matches how a physical keyboard emits shortcut
    events. Requires 2..4 keys, each validated against the same
    allowlist as `key()`.
    """
    if not isinstance(keys, list) or len(keys) < 2 or len(keys) > _MAX_COMBO_KEYS:
        return _err(f"keys must be a list of 2..{_MAX_COMBO_KEYS} names")
    codes: list[str] = []
    for k in keys:
        upper, err = _normalise_key(k)
        if err:
            return _err(err)
        codes.append(f"KEYCODE_{upper}")
    guard = _ensure_adb()
    if guard:
        return guard
    try:
        r = run(
            ["shell", "input", "keyboard", "keycombination", *codes],
            serial=serial, timeout=10,
        )
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"key_combo failed: {e}")
    ok = r.returncode == 0
    return {
        "ok": ok, "action": "key_combo", "keys": codes,
        "stdout": r.stdout, "stderr": r.stderr, "exit_code": r.returncode,
        "error": None if ok else (r.stderr or f"keycombination exit {r.returncode}").strip(),
    }


def scroll(
    serial: str,
    x: int, y: int,
    *,
    vscroll: float = 0.0,
    hscroll: float = 0.0,
) -> dict[str, Any]:
    """Emit a mouse-wheel event at (x, y).

    Uses `adb shell input mouse scroll` with `--axis VSCROLL,N` /
    `--axis HSCROLL,N`. Positive vscroll = scroll content up (like
    a real wheel roll away from you). Coordinates are the current
    rotation's native pixels — same convention as `tap` and `swipe`,
    so the frontend can reuse the same click-to-native math for
    wheel events over the screenshot.

    Not every Android version accepts `mouse scroll`; when it doesn't,
    the fallback is a short `input swipe` in the corresponding
    direction. We prefer the native scroll because it lands as a
    real MotionEvent.ACTION_SCROLL that scrollable views receive
    without any timing tricks.
    """
    for name, val in (("x", x), ("y", y)):
        if not isinstance(val, int):
            return _err(f"{name} must be an integer")
    if x < 0 or y < 0 or x > 100_000 or y > 100_000:
        return _err(f"scroll coordinates out of range: ({x}, {y})")
    if not (isinstance(vscroll, (int, float)) and isinstance(hscroll, (int, float))):
        return _err("vscroll and hscroll must be numeric")
    if vscroll == 0 and hscroll == 0:
        return _err("at least one of vscroll / hscroll must be non-zero")
    for name, val in (("vscroll", vscroll), ("hscroll", hscroll)):
        if abs(val) > 100:
            return _err(f"{name} out of range: {val} (max ±100)")

    guard = _ensure_adb()
    if guard:
        return guard

    args = ["shell", "input", "mouse", "scroll", str(x), str(y)]
    if vscroll:
        args += ["--axis", f"VSCROLL,{vscroll}"]
    if hscroll:
        args += ["--axis", f"HSCROLL,{hscroll}"]
    try:
        r = run(args, serial=serial, timeout=10)
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"scroll failed: {e}")

    # `input mouse scroll` returns 0 on modern Android, but on older
    # versions (or ROMs that reject the mouse source) it exits 255
    # with "Error: Unknown command". Auto-fall-back to a swipe so the
    # caller still gets a visible scroll.
    ok = r.returncode == 0
    if not ok:
        stderr = (r.stderr or "").strip()
        if "unknown" in stderr.lower() or "not found" in stderr.lower() or r.returncode == 255:
            # Simulate a wheel notch as a short swipe. 1 notch ≈ 300 px
            # on a modern high-density display; scale by |vscroll|.
            magnitude = int(abs(vscroll) * 300) or 300
            direction = -1 if vscroll > 0 else 1  # positive vscroll = content up
            fallback = swipe(
                serial, x, y, x, y + direction * magnitude, duration_ms=180,
            )
            fallback = dict(fallback)
            fallback["action"] = "scroll"
            fallback["fallback"] = "swipe"
            fallback["vscroll"] = vscroll
            fallback["hscroll"] = hscroll
            return fallback
    return {
        "ok": ok, "action": "scroll",
        "x": x, "y": y, "vscroll": vscroll, "hscroll": hscroll,
        "stdout": r.stdout, "stderr": r.stderr, "exit_code": r.returncode,
        "error": None if ok else (r.stderr or f"scroll exit {r.returncode}").strip(),
    }

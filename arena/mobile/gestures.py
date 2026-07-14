"""High-level gesture primitives on top of `adb shell input swipe`.

The bare `swipe` primitive in `arena.mobile.input` is only two points and
a duration — good enough for a pixel-perfect drag, but agents (and the
Dashboard) generally want semantic gestures like "pull down the
notification shade" or "scroll one screen up" without hardcoding native
pixel maths.

Everything here reuses `input.swipe` under the hood so validation,
security guards and adb-not-installed handling stay in one place.
"""
from __future__ import annotations

from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run
from arena.mobile.input import swipe as _low_swipe

# The gesture allowlist is deliberately small and closed. Agents that
# want unusual gestures still have the raw /swipe endpoint. This lets
# the Dashboard show a clean set of buttons and keeps audit records
# semantic ("mobile.gesture: notifications") instead of anonymous
# swipes.
_ALLOWED_GESTURES: frozenset[str] = frozenset({
    "notifications",     # pull the notification shade down from the top
    "quick_settings",    # pull twice / drag further to expose tiles
    "close_shade",       # swipe the shade back up
    "scroll_up",         # bottom→top (page contents move down = we see content above)
    "scroll_down",       # top→bottom (page contents move up = we see content below)
    "scroll_left",       # right→left (next page)
    "scroll_right",      # left→right (previous page)
    "back_edge_left",    # gesture-nav back from left edge
    "back_edge_right",   # gesture-nav back from right edge (some HyperOS setups)
    "home_gesture",      # gesture-nav home swipe from bottom center
    "recents_gesture",   # gesture-nav recents swipe up + hold (implemented as long swipe)
})


def allowed_gestures() -> list[str]:
    """Sorted list of gesture names — used by handlers to build error hints."""
    return sorted(_ALLOWED_GESTURES)


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _screen_size(serial: str) -> tuple[int, int] | None:
    """Best-effort screen size lookup via `wm size`. Returns (w, h) or None.

    Used only to translate normalised 0..1 gesture coordinates into device
    pixels. If it fails we fall back to a conservative 1080x2400 default
    (works on almost any modern phone since the resulting swipe still hits
    the intended region on smaller screens — the coords are scaled to
    percentages internally).
    """
    if find_adb() is None:
        return None
    try:
        r = run(["shell", "wm", "size"], serial=serial, timeout=5)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    override: tuple[int, int] | None = None
    physical: tuple[int, int] | None = None
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        value = value.strip()
        if "x" not in value:
            continue
        try:
            w_str, h_str = value.split("x", 1)
            w, h = int(w_str), int(h_str.split()[0])
        except (ValueError, IndexError):
            continue
        if "Override" in label:
            override = (w, h)
        elif "Physical" in label:
            physical = (w, h)
    # HyperOS/POCO expose an Override size when the user picked a scaled
    # resolution in Settings — that is the value `input tap/swipe` uses.
    return override or physical


# ---------------------------------------------------------------------------
# Per-gesture coordinate recipes.
# All coordinates are given as 0..1 fractions of the screen and then
# translated to pixels by `perform()`. Duration is in milliseconds.
# ---------------------------------------------------------------------------
_RECIPES: dict[str, tuple[float, float, float, float, int]] = {
    #                  x1     y1     x2     y2     ms
    "notifications":  (0.50, 0.005, 0.50, 0.500, 350),
    "quick_settings": (0.50, 0.005, 0.50, 0.850, 500),
    "close_shade":    (0.50, 0.900, 0.50, 0.010, 350),
    "scroll_up":      (0.50, 0.750, 0.50, 0.250, 300),
    "scroll_down":    (0.50, 0.250, 0.50, 0.750, 300),
    "scroll_left":    (0.850, 0.50, 0.150, 0.50, 300),
    "scroll_right":   (0.150, 0.50, 0.850, 0.50, 300),
    "back_edge_left": (0.005, 0.50, 0.350, 0.50, 250),
    "back_edge_right":(0.995, 0.50, 0.650, 0.50, 250),
    "home_gesture":   (0.50, 0.995, 0.50, 0.550, 250),
    # Recents on gesture-nav = swipe up from the bottom center and pause.
    # We can't literally "pause" mid-swipe from `input swipe`, but a slow
    # short swipe combined with a stop 60% up the screen works reliably
    # on Android 12+ / HyperOS.
    "recents_gesture":(0.50, 0.995, 0.50, 0.400, 600),
}


def perform(serial: str, gesture: str) -> dict[str, Any]:
    """Run a named gesture on the given device.

    Delegates to `arena.mobile.input.swipe` for the actual send so
    validation and error shape stay identical to the manual swipe path.
    """
    if not isinstance(gesture, str):
        return _err("gesture must be a string")
    key = gesture.strip().lower()
    if key not in _ALLOWED_GESTURES:
        return _err(
            f"gesture {gesture!r} is not on the allowlist",
            hint=f"Allowed gestures: {allowed_gestures()}",
        )
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}

    # Fallback size matches a modern 1080p portrait phone. `swipe` inside
    # input.py clamps and validates in absolute pixels — we just need
    # something sane.
    size = _screen_size(serial) or (1080, 2400)
    width, height = size
    fx1, fy1, fx2, fy2, dur = _RECIPES[key]
    x1 = max(0, min(width - 1, int(round(fx1 * width))))
    y1 = max(0, min(height - 1, int(round(fy1 * height))))
    x2 = max(0, min(width - 1, int(round(fx2 * width))))
    y2 = max(0, min(height - 1, int(round(fy2 * height))))

    try:
        res = _low_swipe(serial, x1, y1, x2, y2, duration_ms=dur)
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"gesture failed: {e}")

    # Repackage under a gesture-shaped envelope so the audit trail and
    # the Dashboard error box can show semantic context, not just raw
    # coordinates.
    res = dict(res)
    res["action"] = "gesture"
    res["gesture"] = key
    res["screen_size"] = [width, height]
    return res

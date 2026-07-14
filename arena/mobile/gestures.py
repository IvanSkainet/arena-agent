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
    # HyperOS/MIUI has a SPLIT notification shade: pulling from the top-
    # left opens notifications, pulling from the top-right opens Quick
    # Settings. Stock Android and older MIUI use the whole top edge for
    # notifications and require a second pull for QS.
    "notifications",      # top-LEFT swipe down (HyperOS/MIUI split)
    "quick_settings",     # top-RIGHT swipe down (HyperOS/MIUI split)
    "shade_center",       # top-CENTER swipe down (stock Android)
    "shade_full",         # top-CENTER long swipe (stock: notifications + QS)
    "close_shade",        # bottom→top swipe over the whole screen
    "scroll_up", "scroll_down", "scroll_left", "scroll_right",
    "back_edge_left",     # gesture-nav back from left edge
    "back_edge_right",    # gesture-nav back from right edge
    "home_gesture",       # gesture-nav home swipe from bottom center
    "recents_gesture",    # gesture-nav recents swipe up + pause
    "screenshot_gesture", # three-finger swipe down (MIUI/HyperOS); best-effort
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
# Coordinate recipes are 0..1 fractions of the *current-rotation* screen
# and are translated to native pixels at call time. Every recipe was
# validated against the POCO F7 Pro (Android 16 / HyperOS OS3.0).
#
# Notes on start-Y values for shade pulls: on HyperOS the split-shade
# activation zone starts just below the status bar cutout (~48px on a
# 3200px-tall portrait screen, ~1.5% of height), so we start at 0.02
# rather than 0.005 — starting AT the very top edge sometimes catches
# the notch region and does nothing.
_RECIPES: dict[str, tuple[float, float, float, float, int]] = {
    #                   x1      y1      x2      y2      ms
    "notifications":   (0.15, 0.02, 0.15, 0.60, 400),   # top-left swipe
    "quick_settings":  (0.85, 0.02, 0.85, 0.60, 400),   # top-right swipe
    "shade_center":    (0.50, 0.02, 0.50, 0.60, 400),   # stock Android
    "shade_full":      (0.50, 0.02, 0.50, 0.90, 500),   # notifications + QS in one pull
    "close_shade":     (0.50, 0.98, 0.50, 0.02, 400),   # bottom → top
    "scroll_up":       (0.50, 0.75, 0.50, 0.25, 300),
    "scroll_down":     (0.50, 0.25, 0.50, 0.75, 300),
    "scroll_left":     (0.85, 0.50, 0.15, 0.50, 300),
    "scroll_right":    (0.15, 0.50, 0.85, 0.50, 300),
    "back_edge_left":  (0.005, 0.50, 0.35, 0.50, 250),
    "back_edge_right": (0.995, 0.50, 0.65, 0.50, 250),
    "home_gesture":    (0.50, 0.995, 0.50, 0.55, 250),
    "recents_gesture": (0.50, 0.995, 0.50, 0.40, 600),
    # Three-finger screenshot is a MIUI-specific gesture; `input swipe`
    # doesn't do multi-touch, so we approximate with a triangle-shaped
    # short drag near screen centre. Might not fire on all HyperOS
    # builds — treat as best-effort. Fallback: `key POWER`+`VOLUME_DOWN`
    # combo from the caller side.
    "screenshot_gesture": (0.50, 0.40, 0.50, 0.60, 350),
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

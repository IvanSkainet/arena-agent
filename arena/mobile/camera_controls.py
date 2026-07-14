"""v3.84.4: mode/lens/zoom/flash + video record + raw controls dump.

Split out of `arena.mobile.camera` to keep both files well under the
700-line product cap. This module deliberately owns everything that
depends on live UI introspection (uiautomator dumps + tap by
resource-id / content-desc) so a future refactor can swap the
introspection layer in one place.

All entry points return the same `{ok: bool, ...}` shape as the rest
of arena.mobile and never raise -- they trap and package errors so
the HTTP handlers can pass them through unchanged.
"""
from __future__ import annotations

import re
import time
from typing import Any

from arena.mobile import camera as _cam
from arena.mobile.input import tap as _tap


# Per-serial cache of the last successfully detected shutter position.
# When the camera preview covers the whole screen with a GL surface
# (common on HyperOS during video recording) `uiautomator dump`
# sometimes returns an empty tree -- in that case record_stop needs
# to fall back to the last known-good coordinates rather than fail.
_SHUTTER_CACHE: dict[str, tuple[int, int, float]] = {}
_SHUTTER_CACHE_TTL_SEC = 300.0


def _remember_shutter(serial: str, x: int, y: int) -> None:
    _SHUTTER_CACHE[serial] = (int(x), int(y), time.time())


def _recall_shutter(serial: str) -> tuple[int, int] | None:
    hit = _SHUTTER_CACHE.get(serial)
    if not hit:
        return None
    x, y, ts = hit
    if time.time() - ts > _SHUTTER_CACHE_TTL_SEC:
        _SHUTTER_CACHE.pop(serial, None)
        return None
    return x, y


def _shutter_tap(serial: str, *, retries: int = 2,
                 retry_delay: float = 1.5) -> dict[str, Any]:
    """Wrap camera.shutter() with a cache + short retry loop.

    Real-world failure modes we defend against here:

    * `uiautomator dump` returns an empty tree during video recording
      (HyperOS sometimes hides the accessibility tree behind a GL
      surface). -> use cached shutter coordinates from a prior call to
      `list_controls` / any earlier successful detection.

    * The device flips to `offline` / `authorizing` for a second or
      two around dumps (loose USB, ADB heartbeat glitch). -> retry the
      tap; ADB usually recovers within ~1.5s.
    """
    last: dict[str, Any] = {"ok": False, "error": "shutter tap not attempted"}
    for attempt in range(max(1, retries + 1)):
        live = _cam.shutter(serial)
        if live.get("ok") and live.get("shutter_x") is not None:
            _remember_shutter(serial, live["shutter_x"], live["shutter_y"])
            return live
        last = live
        cached = _recall_shutter(serial)
        if cached is not None:
            x, y = cached
            r = _tap(serial, x, y)
            r = dict(r)
            r["action"] = "shutter"
            r["shutter_x"] = x
            r["shutter_y"] = y
            r["detected_via"] = "cached (fallback: live dump failed)"
            r["ok"] = bool(r.get("ok", True)) and not r.get("error")
            if r["ok"]:
                return r
            last = r
        if attempt < retries:
            time.sleep(retry_delay)
    return last


# Localized labels for the mode strip. Keys are the canonical mode
# name accepted by `switch_mode`; values are every text / content-desc
# variant seen on shipping ROMs.
_MODE_ALIASES: dict[str, tuple[str, ...]] = {
    "photo":    ("Photo", "Camera", "Фото", "Foto"),
    "video":    ("Video", "Видео"),
    "portrait": ("Portrait", "Портрет"),
    "pro":      ("Pro", "Manual", "Профи"),
    "night":    ("Night", "Ночь"),
    "document": ("Document", "Documents", "Документ", "Документы"),
    "slowmo":   ("Slow motion", "Замедл", "Slowmo"),
    "timelapse": ("Time-lapse", "Time lapse", "Таймлапс", "Интервал"),
    "pano":     ("Pano", "Panorama", "Панорама"),
    "short":    ("Short video", "Короткое видео"),
    "movie":    ("Movie", "Кино"),
}

_FLASH_ALIASES: dict[str, tuple[str, ...]] = {
    "auto":  ("Auto", "Авто"),
    "on":    ("On", "Вкл", "Включ"),
    "off":   ("Off", "Выкл", "Выключ"),
    "torch": ("Torch", "Фонарь"),
}


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _resolve_alias(name: str, table: dict[str, tuple[str, ...]]
                   ) -> tuple[str, tuple[str, ...]] | None:
    key = (name or "").strip().lower()
    if key in table:
        return key, table[key]
    for k, aliases in table.items():
        if any(a.lower() == key for a in aliases):
            return k, aliases
    return None


# ---------------------------------------------------------------------------
# Raw controls dump
# ---------------------------------------------------------------------------

def list_controls(serial: str) -> dict[str, Any]:
    """Every clickable UI node in the foreground camera app so an AI
    caller can introspect + drive the app by resource-id / desc
    rather than by guessed coordinates."""
    guard = _cam._ensure_adb()
    if guard:
        return guard
    dump, clickable = _cam.iter_clickable(serial)
    if not dump.get("ok"):
        return dump
    controls = []
    for n in clickable:
        c = n.get("center") or [0, 0]
        rid = (n.get("resource-id") or "")
        controls.append({
            "resource_id": rid,
            "content_desc": n.get("content-desc") or "",
            "text": n.get("text") or "",
            "class": n.get("class") or "",
            "bounds": n.get("bounds"),
            "center": [int(c[0]), int(c[1])],
        })
        # Warm the shutter cache while we're here -- if the caller
        # opens /camera/controls before recording, subsequent
        # record_stop calls will survive a blank uiautomator dump.
        if "shutter_button" in rid.lower() and c and c[0] and c[1]:
            _remember_shutter(serial, int(c[0]), int(c[1]))
    return {
        "ok": True,
        "package": dump.get("package"),
        "screen_bounds": dump.get("screen_bounds"),
        "count": len(controls),
        "controls": controls,
        "cached_shutter": _recall_shutter(serial),
    }


# ---------------------------------------------------------------------------
# Mode / lens / zoom / flash
# ---------------------------------------------------------------------------

def switch_mode(serial: str, mode: str) -> dict[str, Any]:
    """Switch the camera app to the requested capture mode."""
    guard = _cam._ensure_adb()
    if guard:
        return guard
    resolved = _resolve_alias(mode, _MODE_ALIASES)
    if not resolved:
        return _err(f"unknown mode {mode!r}",
                    known=sorted(_MODE_ALIASES.keys()))
    canonical, aliases = resolved

    dump, _ = _cam.iter_clickable(serial)
    if not dump.get("ok"):
        return dump

    candidates = []
    for n in dump.get("nodes", []):
        rid = (n.get("resource-id") or "")
        text = (n.get("text") or "")
        desc = (n.get("content-desc") or "")
        label = text or desc
        if not label:
            continue
        if not any(a.lower() == label.lower() or a.lower() in label.lower()
                   for a in aliases):
            continue
        c = n.get("center")
        if not c:
            continue
        rank = 0 if "mode_select_item" in rid else 1
        candidates.append((rank, n, label))

    if not candidates:
        return _err(f"mode {mode!r} not visible in current camera UI",
                    hint="Call /camera/controls to see visible modes.",
                    tried=list(aliases))
    candidates.sort(key=lambda t: t[0])
    _, node, label = candidates[0]
    r = _tap(serial, node["center"][0], node["center"][1])
    r = dict(r)
    r["action"] = "camera_mode"
    r["mode"] = canonical
    r["matched_label"] = label
    r["tap"] = node["center"]
    return r


def switch_lens(serial: str, target: str = "toggle") -> dict[str, Any]:
    """Flip between rear and front cameras.

    `target`: `toggle` / `front` / `back`. front/back inspect
    content-desc to decide whether a tap is even needed.
    """
    guard = _cam._ensure_adb()
    if guard:
        return guard
    dump, _ = _cam.iter_clickable(serial)
    if not dump.get("ok"):
        return dump

    picker = None
    for n in dump.get("nodes", []):
        rid = (n.get("resource-id") or "").lower()
        desc = (n.get("content-desc") or "").lower()
        if ("camera_picker" in rid or "switch_camera" in rid
                or "lens_switch" in rid
                or "switch camera" in desc or "переключение камеры" in desc):
            picker = n
            break
    if not picker:
        return _err("no lens-switch control found",
                    hint="Call /camera/controls to inspect the current UI.")

    desc = (picker.get("content-desc") or "").lower()
    is_back = any(m in desc for m in ("задний", "back", "rear"))
    is_front = any(m in desc for m in ("передний", "front"))

    target = (target or "toggle").lower()
    if target == "front" and is_front:
        return {"ok": True, "action": "lens_switch",
                "already": "front", "content_desc": picker.get("content-desc")}
    if target == "back" and is_back:
        return {"ok": True, "action": "lens_switch",
                "already": "back", "content_desc": picker.get("content-desc")}

    c = picker.get("center")
    if not c:
        return _err("lens switch has no bounds")
    r = _tap(serial, c[0], c[1])
    r = dict(r)
    r["action"] = "lens_switch"
    r["target"] = target
    r["was"] = "back" if is_back else ("front" if is_front else "unknown")
    r["tap"] = c
    return r


def set_zoom(serial: str, level: str | float) -> dict[str, Any]:
    """Tap the requested zoom chip (0.6, 1.0, 2.0, ...)."""
    guard = _cam._ensure_adb()
    if guard:
        return guard
    try:
        want = float(level)
    except (TypeError, ValueError):
        return _err(f"level must be a number, got {level!r}")
    dump, _ = _cam.iter_clickable(serial)
    if not dump.get("ok"):
        return dump

    best = None
    for n in dump.get("nodes", []):
        desc = (n.get("content-desc") or "")
        text = (n.get("text") or "")
        label = desc or text
        if not label:
            continue
        rid = (n.get("resource-id") or "").lower()
        # Only consider nodes that are visibly zoom-related.
        if "zoom" not in rid and "zoom" not in desc.lower() \
                and "приближение" not in desc.lower():
            continue
        nums = [float(m.group()) for m in
                re.finditer(r"\d+(?:[\.,]\d+)?", label.replace(",", "."))]
        if not nums:
            continue
        for v in nums:
            diff = abs(v - want)
            if best is None or diff < best[0]:
                best = (diff, n, label, v)
    if best is None:
        return _err(f"no zoom chip near {want}x found",
                    hint="Call /camera/controls; some apps hide zoom "
                         "chips until you pinch the preview once.")
    _, node, label, matched = best
    c = node["center"]
    r = _tap(serial, c[0], c[1])
    r = dict(r)
    r["action"] = "camera_zoom"
    r["requested"] = want
    r["matched"] = matched
    r["label"] = label
    return r


def set_flash(serial: str, mode: str) -> dict[str, Any]:
    """Set flash mode. `mode`: auto / on / off / torch."""
    guard = _cam._ensure_adb()
    if guard:
        return guard
    resolved = _resolve_alias(mode, _FLASH_ALIASES)
    if not resolved:
        return _err(f"unknown flash mode {mode!r}",
                    known=sorted(_FLASH_ALIASES.keys()))
    canonical, aliases = resolved
    dump, _ = _cam.iter_clickable(serial)
    if not dump.get("ok"):
        return dump

    flash_btn = None
    for n in dump.get("nodes", []):
        desc = (n.get("content-desc") or "").lower()
        rid = (n.get("resource-id") or "").lower()
        if "flash" in rid or "flash" in desc or "вспышк" in desc:
            flash_btn = n
            break
    if not flash_btn:
        return _err("no flash control found in current camera UI")

    cur_desc = (flash_btn.get("content-desc") or "").lower()
    if any(a.lower() in cur_desc for a in aliases):
        return {"ok": True, "action": "camera_flash",
                "mode": canonical, "already": True,
                "content_desc": flash_btn.get("content-desc")}

    c = flash_btn.get("center")
    if not c:
        return _err("flash button has no bounds")
    _tap(serial, c[0], c[1])
    time.sleep(0.4)
    dump2, _ = _cam.iter_clickable(serial)
    if not dump2.get("ok"):
        return dump2
    for n in dump2.get("nodes", []):
        desc = (n.get("content-desc") or "")
        text = (n.get("text") or "")
        label = desc or text
        if not label:
            continue
        if any(a.lower() == label.lower() or a.lower() in label.lower()
               for a in aliases):
            cc = n.get("center")
            if not cc:
                continue
            r = _tap(serial, cc[0], cc[1])
            r = dict(r)
            r["action"] = "camera_flash"
            r["mode"] = canonical
            r["matched_label"] = label
            return r
    return _err(f"flash option {canonical!r} not visible after opening menu",
                hint="Some apps rearrange flash options; retry after switching to photo mode.")


# ---------------------------------------------------------------------------
# Video record via UI (uses the in-app codec, not raw screenrecord)
# ---------------------------------------------------------------------------

def _newest_media(serial: str) -> tuple[str | None, float]:
    r = _cam.list_photos(serial, limit=1)
    if not r.get("ok"):
        return None, 0.0
    photos = r.get("photos") or []
    if not photos:
        return None, 0.0
    p = photos[0]
    return p["path"], _cam.photo_mtime(serial, p["path"])


def _newest_video(serial: str) -> tuple[str | None, float]:
    """Return (path, mtime) of the newest .mp4/.mov file in DCIM,
    ignoring photos entirely. record_stop needs to spot the MP4 the
    camera app just finalised even when a photo happened to be
    written to the same directory more recently (e.g. from a
    concurrent shutter tap or a MotionPhoto still)."""
    r = _cam.list_photos(serial, limit=30)
    if not r.get("ok"):
        return None, 0.0
    for p in r.get("photos") or []:
        name = (p.get("name") or "").lower()
        if name.endswith((".mp4", ".mov", ".mkv", ".webm", ".3gp")):
            return p["path"], _cam.photo_mtime(serial, p["path"])
    return None, 0.0


def _detect_recording(serial: str) -> str | None:
    """Return the content-desc of the shutter if it currently reads as
    a Stop button (i.e. recording is in progress), else None."""
    dump, _ = _cam.iter_clickable(serial)
    if not dump.get("ok"):
        return None
    for n in dump.get("nodes", []):
        desc = (n.get("content-desc") or "").lower()
        if not desc:
            continue
        if ("stop" in desc or "остановить" in desc or "стоп" in desc
                or "запись остан" in desc):
            return n.get("content-desc")
    return None


def record_start(serial: str, *,
                 wait_after_mode_ms: int = 900,
                 wait_after_shutter_ms: int = 500) -> dict[str, Any]:
    """Switch to video mode and press the shutter to start recording.

    Idempotent: if the shutter already reads as 'Stop' this returns
    ok=True with `already_recording=True` and does not tap again.
    """
    guard = _cam._ensure_adb()
    if guard:
        return guard

    ongoing = _detect_recording(serial)
    if ongoing:
        return {"ok": True, "action": "record_start",
                "already_recording": True, "content_desc": ongoing}

    mode = switch_mode(serial, "video")
    time.sleep(max(0, wait_after_mode_ms) / 1000.0)

    tapped = _shutter_tap(serial)
    if not tapped.get("ok"):
        return _err("could not tap shutter to start recording",
                    stage="shutter", detail=tapped)
    time.sleep(max(0, wait_after_shutter_ms) / 1000.0)

    verified = _detect_recording(serial) is not None
    return {
        "ok": True,
        "action": "record_start",
        "mode_switch": mode,
        "verified_recording": verified,
        "shutter": {"x": tapped.get("shutter_x"),
                    "y": tapped.get("shutter_y"),
                    "detected_via": tapped.get("detected_via")},
    }


def record_stop(serial: str, *,
                wait_for_file_ms: int = 12000,
                pull: bool = False,
                max_size: int | None = None,
                format: str = "jpeg",
                quality: int = 85) -> dict[str, Any]:
    """Tap the shutter to stop recording and wait for the resulting MP4.

    If `pull=True` the MP4 bytes are returned base64-encoded.
    """
    guard = _cam._ensure_adb()
    if guard:
        return guard
    # We're looking for a FRESH .mp4 to appear, not just any DCIM
    # write -- HyperOS occasionally drops a MotionPhoto still into
    # the same directory during a recording, and using
    # `_newest_media` as the baseline lets that still shadow the
    # real video file. Track videos separately.
    baseline_path, baseline_mtime = _newest_video(serial)

    tapped = _shutter_tap(serial)
    if not tapped.get("ok"):
        return _err("could not tap shutter to stop recording",
                    stage="shutter", detail=tapped)

    deadline = time.monotonic() + wait_for_file_ms / 1000.0
    fresh_path = None
    fresh_size = 0
    while time.monotonic() < deadline:
        cur_path, cur_mtime = _newest_video(serial)
        if cur_path and (cur_path != baseline_path
                         or cur_mtime > baseline_mtime + 0.1):
            fresh_path = cur_path
            fresh_size = _cam.photo_size(serial, cur_path)
            break
        time.sleep(0.4)

    result: dict[str, Any] = {
        "ok": True,
        "action": "record_stop",
        "shutter": {"x": tapped.get("shutter_x"),
                    "y": tapped.get("shutter_y"),
                    "detected_via": tapped.get("detected_via")},
        "video_path": fresh_path,
        "size_bytes": fresh_size,
    }
    if not fresh_path:
        result["ok"] = False
        result["error"] = "no new video appeared in DCIM before timeout"
        result["waited_ms"] = wait_for_file_ms
        result["baseline_path"] = baseline_path
        return result

    if pull:
        # Wait for file size to stabilise (encoder finalising moov).
        prev = -1
        for _ in range(25):
            cur = _cam.photo_size(serial, fresh_path)
            if cur == prev and cur > 0:
                break
            prev = cur
            time.sleep(0.4)
        pulled = _cam.pull_photo(serial, fresh_path,
                                 max_size=max_size, format=format,
                                 quality=quality)
        if pulled.get("ok"):
            result["bytes_b64"] = pulled.get("bytes_b64")
            result["mime"] = pulled.get("mime") or "video/mp4"
            result["size_bytes"] = pulled.get("size_bytes") or fresh_size
    return result

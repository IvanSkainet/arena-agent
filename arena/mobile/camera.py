"""Camera automation via intents + shutter tap + latest-photo pull.

Android doesn't let a userspace ADB caller directly trigger the shutter
of a foreground camera app — `KEYCODE_CAMERA` and `KEYCODE_FOCUS` are
privileged on modern releases (13+), and `KEYCODE_VOLUME_DOWN` is only
mapped to shutter in some camera apps (Google Camera yes, MIUI Camera
no). The reliable path is:

  1. Launch the camera app via `am start -a
     android.media.action.STILL_IMAGE_CAMERA`.
  2. Wait for the camera preview to be ready.
  3. Tap the shutter button — either at explicit coordinates the
     caller supplied, or auto-detected from a `uiautomator dump`
     looking for a clickable node with `shutter` / `capture` in its
     resource-id.
  4. Wait for the new photo to land in `/sdcard/DCIM/**`.
  5. Optionally pull the file back to the bridge, optionally downscale.

Everything here is best-effort. Some camera apps take 1-3 s to encode
a photo, so `capture_and_pull` polls the DCIM directory for a new
file until timeout.
"""
from __future__ import annotations

import base64
import io
import re
import time
from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run
from arena.mobile.input import tap as _tap

# Common paths where camera apps drop photos. First match wins for
# `list_photos`; capture_and_pull scans the full list.
_DCIM_PATHS = (
    "/sdcard/DCIM/Camera",
    "/sdcard/DCIM",
    "/storage/emulated/0/DCIM/Camera",
    "/storage/emulated/0/Pictures",
)

# Image intents the caller can pick from.
_INTENTS = {
    "still": "android.media.action.STILL_IMAGE_CAMERA",   # user-driven capture
    "video": "android.media.action.VIDEO_CAMERA",         # video mode
    "generic": "android.intent.action.CAMERA_BUTTON",     # some apps listen for this
}

# resource-id heuristics for the shutter button in the auto-detect path.
_SHUTTER_HINTS = ("shutter", "capture", "take_picture", "click_photo",
                  "photo_button", "camera_button")


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _ensure_adb() -> dict[str, Any] | None:
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}
    return None


def _sh(serial: str, args: list[str], timeout: int = 10) -> tuple[int, str, str]:
    try:
        r = run(["shell", *args], serial=serial, timeout=timeout)
    except Exception as e:
        return (255, "", str(e))
    return (r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip())


# ---------------------------------------------------------------------------
# Launch + shutter
# ---------------------------------------------------------------------------

def launch(serial: str, *, intent: str = "still",
           package: str | None = None) -> dict[str, Any]:
    """Start the camera app via an implicit intent.

    Args:
      intent: `still` (default), `video`, or `generic`.
      package: optional explicit package to prefer (e.g.
        `com.google.android.GoogleCamera`, `com.android.camera`).
        Without this Android's resolver picks the user's default
        camera app.
    """
    if intent not in _INTENTS:
        return _err(f"unknown intent {intent!r}",
                    hint=f"Allowed: {sorted(_INTENTS)}")
    guard = _ensure_adb()
    if guard:
        return guard

    args = ["am", "start", "-a", _INTENTS[intent]]
    if package:
        args += ["-p", package]
    rc, out, err = _sh(serial, args, timeout=15)
    if rc != 0:
        return _err(err or out or f"am start exit {rc}", exit_code=rc)
    if "Error" in out or "not found" in out.lower():
        return _err(out, hint="Is a camera app installed and enabled?")
    return {
        "ok": True,
        "action": "camera_launch",
        "intent": _INTENTS[intent],
        "package": package,
        "stdout": out,
    }


def find_shutter(serial: str) -> dict[str, Any]:
    """Return the on-screen shutter coordinates by inspecting UI
    Automator. Returns `{ok, x, y, resource_id, source}` on success.
    """
    from arena.mobile import ui as _ui
    dump = _ui.dump_ui(serial, interactive_only=False, max_nodes=1000)
    if not dump.get("ok"):
        return dump

    # First pass: exact resource-id hint.
    best_hint = None
    best_generic = None
    for n in dump.get("nodes", []):
        rid = (n.get("resource-id") or "").lower()
        center = n.get("center")
        if not center or len(center) != 2:
            continue
        if n.get("clickable") != "true":
            continue
        for hint in _SHUTTER_HINTS:
            if hint in rid:
                best_hint = (n, hint)
                break
        # Fallback: the biggest clickable node in the bottom quarter,
        # x roughly centered.
        w = dump.get("screen_bounds", [1440, 3200])[0]
        h = dump.get("screen_bounds", [1440, 3200])[1]
        if center[1] > h * 0.75 and 0.3 * w < center[0] < 0.7 * w:
            area = n.get("width", 0) * n.get("height", 0)
            if best_generic is None or area > best_generic[1]:
                best_generic = (n, area)

    if best_hint:
        node, matched = best_hint
        return {
            "ok": True,
            "x": node["center"][0], "y": node["center"][1],
            "resource_id": node.get("resource-id"),
            "source": f"resource-id contains {matched!r}",
        }
    if best_generic:
        node, _ = best_generic
        return {
            "ok": True,
            "x": node["center"][0], "y": node["center"][1],
            "resource_id": node.get("resource-id") or "",
            "source": "largest clickable node in bottom-center quarter",
        }
    return _err(
        "no shutter-shaped node found",
        hint="Is the camera app in the foreground? Try passing "
             "explicit `shutter_x` / `shutter_y` coordinates.",
    )


def shutter(serial: str, *,
            shutter_x: int | None = None,
            shutter_y: int | None = None) -> dict[str, Any]:
    """Tap the shutter button. Uses explicit coords when provided,
    otherwise auto-detects via `find_shutter`."""
    guard = _ensure_adb()
    if guard:
        return guard
    if shutter_x is None or shutter_y is None:
        s = find_shutter(serial)
        if not s.get("ok"):
            return s
        shutter_x, shutter_y = s["x"], s["y"]
        detected_via = s["source"]
    else:
        detected_via = "caller-supplied coordinates"
    r = _tap(serial, int(shutter_x), int(shutter_y))
    r = dict(r)
    r["action"] = "shutter"
    r["shutter_x"] = shutter_x
    r["shutter_y"] = shutter_y
    r["detected_via"] = detected_via
    return r


# ---------------------------------------------------------------------------
# Listing + fetching photos from DCIM
# ---------------------------------------------------------------------------

_LS_LINE = re.compile(
    r"^\S+\s+\d+\s+\S+\s+\S+\s+(?P<size>\d+)\s+"
    r"(?P<date>\S+\s+\S+)\s+(?P<name>.+)$"
)


def list_photos(serial: str, *, limit: int = 10) -> dict[str, Any]:
    """List the newest photos + videos in DCIM. Reports name, path,
    size and modification time for each."""
    guard = _ensure_adb()
    if guard:
        return guard
    entries: list[dict[str, Any]] = []
    for root in _DCIM_PATHS:
        rc, out, _ = _sh(serial, ["ls", "-lt", root], timeout=8)
        if rc != 0 or not out:
            continue
        for line in out.splitlines():
            m = _LS_LINE.match(line.strip())
            if not m:
                continue
            name = m.group("name")
            if name in (".", ".."):
                continue
            entries.append({
                "path": f"{root}/{name}",
                "name": name,
                "size_bytes": int(m.group("size")),
                "modified": m.group("date"),
            })
            if len(entries) >= limit:
                break
        if entries:
            # First DCIM path with content wins to avoid duplicates
            # from bind-mounted /sdcard/DCIM aliases.
            break
    return {"ok": True, "count": len(entries), "photos": entries[:limit]}


def _photo_mtime(serial: str, path: str) -> float:
    """Return `stat -c %Y` (epoch seconds) for the given path, or 0."""
    rc, out, _ = _sh(serial, ["stat", "-c", "%Y", path])
    if rc != 0:
        return 0.0
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def latest_photo(serial: str) -> dict[str, Any]:
    """Return the newest file in DCIM by modification time.

    Used by `capture_and_pull` to identify what the shutter produced —
    we snapshot the newest mtime before shutter, then poll until we
    see a newer file appear.
    """
    r = list_photos(serial, limit=1)
    if not r.get("ok"):
        return r
    photos = r.get("photos") or []
    if not photos:
        return _err("DCIM is empty",
                    hint=f"Checked {list(_DCIM_PATHS)!r}")
    p = photos[0]
    p["mtime_epoch"] = _photo_mtime(serial, p["path"])
    return {"ok": True, **p}


def pull_photo(serial: str, path: str, *,
               max_size: int | None = None,
               format: str = "jpeg",
               quality: int = 85) -> dict[str, Any]:
    """Fetch a photo from the phone. Optionally downscale on the bridge.

    Response:
      {"ok": bool, "bytes": base64_str, "mime": str, "size_bytes": int,
       "source_path": str, "width": int, "height": int}
    """
    guard = _ensure_adb()
    if guard:
        return guard
    if not isinstance(path, str) or not path.startswith("/"):
        return _err("path must be an absolute device path")
    # `adb exec-out cat` streams the file to stdout without base64.
    try:
        r = run(["exec-out", "cat", path], serial=serial,
                timeout=60, capture_binary=True)
    except AdbNotFoundError as e:
        return _err(str(e))
    if r.returncode != 0:
        return _err((r.stderr or b"").decode("utf-8", "replace").strip()
                    or f"cat exit {r.returncode}")
    data = r.stdout or b""
    if not data:
        return _err(f"file empty or missing: {path}")

    width = height = 0
    if max_size or format != "jpeg":
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            img.load()
            width, height = img.width, img.height
            if max_size and int(max_size) > 0:
                long_side = max(width, height)
                if long_side > int(max_size):
                    ratio = int(max_size) / long_side
                    tw, th = max(1, int(width * ratio)), max(1, int(height * ratio))
                    img = img.resize((tw, th), Image.LANCZOS)
                    width, height = tw, th
            buf = io.BytesIO()
            if format == "webp":
                img.save(buf, format="WEBP",
                         quality=max(1, min(100, quality)), method=4)
                mime = "image/webp"
            elif format == "png":
                img.save(buf, format="PNG", optimize=False, compress_level=6)
                mime = "image/png"
            else:
                if img.mode in ("RGBA", "P", "LA"):
                    img = img.convert("RGB")
                img.save(buf, format="JPEG",
                         quality=min(95, max(1, quality)),
                         subsampling=0)
                mime = "image/jpeg"
            data = buf.getvalue()
        except Exception as e:
            return _err(f"downscale failed: {e}",
                        source_path=path, size_bytes=len(data))
    else:
        mime = "image/jpeg"

    return {
        "ok": True,
        "source_path": path,
        "size_bytes": len(data),
        "mime": mime,
        "width": width, "height": height,
        "bytes_b64": base64.b64encode(data).decode("ascii"),
    }


def capture_and_pull(serial: str, *,
                     shutter_x: int | None = None,
                     shutter_y: int | None = None,
                     wait_before_shutter_ms: int = 1500,
                     wait_for_file_ms: int = 5000,
                     max_size: int | None = 1024,
                     format: str = "jpeg",
                     quality: int = 85,
                     package: str | None = None) -> dict[str, Any]:
    """Full flow: launch camera → shutter → poll DCIM → pull result.

    Returns the pulled photo (base64) + a per-step timing report. On
    timeout waiting for the new file we still return the launch/shutter
    outcome so the caller can debug.
    """
    guard = _ensure_adb()
    if guard:
        return guard
    started = time.monotonic()
    baseline = latest_photo(serial)
    baseline_path = baseline.get("path") if baseline.get("ok") else None
    baseline_mtime = baseline.get("mtime_epoch", 0.0)

    launched = launch(serial, intent="still", package=package)
    if not launched.get("ok"):
        return _err("failed to launch camera",
                    stage="launch", detail=launched)

    time.sleep(max(0, wait_before_shutter_ms) / 1000.0)

    tapped = shutter(serial, shutter_x=shutter_x, shutter_y=shutter_y)
    if not tapped.get("ok"):
        return _err("shutter tap failed", stage="shutter", detail=tapped)

    # Poll DCIM for a new file with mtime > baseline.
    deadline = time.monotonic() + wait_for_file_ms / 1000.0
    fresh_path = None
    fresh_size = 0
    while time.monotonic() < deadline:
        current = latest_photo(serial)
        if current.get("ok"):
            path = current["path"]
            mtime = current.get("mtime_epoch", 0.0)
            # A new file, or the same "latest" name but with a bigger
            # mtime and a bigger size (some ROMs write with a stub then
            # append EXIF, keeping the same filename).
            if path != baseline_path or mtime > baseline_mtime + 0.1:
                fresh_path = path
                fresh_size = current.get("size_bytes") or 0
                break
        time.sleep(0.25)

    total_launch_ms = int((time.monotonic() - started) * 1000)
    if not fresh_path:
        return _err(
            "no new photo appeared in DCIM before timeout",
            stage="poll",
            hint=("Camera may be showing a permission or 'save to' "
                  "dialog. Screenshot the phone and inspect."),
            waited_ms=wait_for_file_ms,
            baseline_path=baseline_path,
        )

    pulled = pull_photo(serial, fresh_path,
                        max_size=max_size, format=format, quality=quality)
    if not pulled.get("ok"):
        return pulled
    pulled["total_duration_ms"] = int((time.monotonic() - started) * 1000)
    pulled["shutter"] = {"x": tapped["shutter_x"], "y": tapped["shutter_y"],
                         "detected_via": tapped["detected_via"]}
    pulled["launch_intent"] = launched["intent"]
    return pulled

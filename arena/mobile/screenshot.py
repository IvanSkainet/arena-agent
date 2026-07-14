"""Device screenshot capture via `adb exec-out screencap`.

v3.83.4 speed overhaul:
  * **Raw bitmap path** (default). `adb exec-out screencap` (no `-p`)
    returns the framebuffer as a 12/16-byte header + ARGB_8888 pixel
    buffer, which Pillow's `frombuffer` decodes without going through
    the PNG encoder on the phone. On the reference POCO F7 Pro this
    is ~2× faster than `-p` because Android skips its own PNG encoding
    (~1500 ms saved per frame).
  * PNG path kept as a fallback for devices that don't return a
    parseable raw header (rare, mostly older Android <10 or fringe
    ROMs). Falls back automatically when the header validation fails.
  * `FLAG_SECURE` detection — some screens (password entry, banking
    apps, DRM video) are marked secure and `screencap` returns a
    black frame instead of the real content. We detect this by
    inspecting the returned frame and surface a hint so the user
    doesn't think the bridge is broken.

Response shape:
  {"ok": bool, "bytes": bytes, "mime": str, "width": int, "height": int,
   "source_width": int, "source_height": int, "size_bytes": int,
   "downscaled": bool, "format": str, "quality": int | None,
   "capture_mode": "raw"|"png", "capture_ms": int,
   "encode_ms": int, "secure_frame": bool | None,
   "error": str | None}
"""
from __future__ import annotations

import io
import struct
import time
from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run

# Modern Android (10+) uses a 16-byte header; some older builds still
# emit a 12-byte header. Both are supported. Format ints:
#   1 = HAL_PIXEL_FORMAT_RGBA_8888
#   2 = RGBX_8888
#   3 = RGB_888
#   5 = BGRA_8888  (occasional weird ROMs)
_PIXEL_FORMATS: dict[int, tuple[str, int]] = {
    1: ("RGBA", 4),
    2: ("RGBA", 4),   # RGBX treated as RGBA with alpha ignored
    3: ("RGB",  3),
    5: ("BGRA", 4),
}


def capture(
    serial: str,
    *,
    max_width: int | None = None,
    max_size: int | None = None,
    quality: int = 85,
    format: str = "png",
    force_png_source: bool = False,
) -> dict[str, Any]:
    """Capture a screenshot from the device.

    Args:
      max_size: downscale so long side <= max_size (preferred; works
        for both portrait and landscape).
      max_width: legacy — downscale so WIDTH <= max_width. `max_size`
        wins when both are set.
      quality: encoder quality (1-95 JPEG, 1-100 WebP).
      format: "png" (default), "jpeg", "webp".
      force_png_source: skip the fast raw-bitmap path and use
        `screencap -p` directly. Useful for tests and for devices
        that emit a malformed raw header.
    """
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}

    # Fast path: `screencap` without `-p` streams the raw framebuffer.
    # Skipping the on-device PNG encoder is the single biggest latency
    # win — ~1500 ms per frame on POCO F7 Pro.
    if not force_png_source:
        r = _try_raw_capture(serial)
        if r is not None:
            return _postprocess(r, max_width=max_width, max_size=max_size,
                                quality=quality, format=format)

    # Fallback: `-p` gets a PNG we can decode with Pillow.
    return _capture_png(serial, max_width=max_width, max_size=max_size,
                        quality=quality, format=format)


def _try_raw_capture(serial: str) -> dict[str, Any] | None:
    """Attempt the fast raw path. Returns None to indicate the caller
    should fall back to PNG; returns a partially-populated result dict
    (with `pixels` array + `source_width/height`) on success."""
    started = time.monotonic()
    try:
        r = run(["exec-out", "screencap"], serial=serial, timeout=20,
                capture_binary=True)
    except AdbNotFoundError:
        raise
    except Exception:
        return None
    capture_ms = int((time.monotonic() - started) * 1000)
    if r.returncode != 0 or not r.stdout:
        return None
    raw = r.stdout

    parsed = _parse_raw_header(raw)
    if not parsed:
        return None
    w, h, mode, bpp, header_len = parsed
    expected = w * h * bpp
    payload = raw[header_len : header_len + expected]
    if len(payload) < expected:
        # Truncated. Fall back to PNG so we don't ship a corrupt frame.
        return None

    try:
        from PIL import Image  # type: ignore
    except Exception:
        # No Pillow means we can't decode raw. Fall back to PNG which
        # the browser can render directly.
        return None
    try:
        img = Image.frombuffer(mode, (w, h), payload, "raw", mode, 0, 1)
        if mode == "BGRA":
            # Split + reassemble to swap channels. Cheap on modern Pillow.
            b, g, r_, a = img.split()
            img = Image.merge("RGBA", (r_, g, b, a))
            mode = "RGBA"
    except Exception:
        return None

    # `secure_frame` detection: for a screen that's flagged FLAG_SECURE
    # (password entry, most banking apps, DRM), `screencap` returns an
    # all-black frame instead of the actual content. Sample a few pixels
    # from the middle-ish rows — a real screen almost never has zero
    # variance there. This adds ~1 ms.
    secure = _looks_secure_frame(img)

    return {
        "ok": True,
        "_pil_image": img,
        "source_width": w,
        "source_height": h,
        "capture_ms": capture_ms,
        "capture_mode": "raw",
        "secure_frame": secure,
    }


def _parse_raw_header(raw: bytes) -> tuple[int, int, str, int, int] | None:
    """Return (width, height, pil_mode, bytes_per_pixel, header_len) or None."""
    if len(raw) < 16:
        return None
    # Try the 16-byte header first (Android 10+). If the color-space
    # field is a plausible enum (0..7) and format is known, accept it.
    try:
        w16, h16, fmt16, cs16 = struct.unpack("<IIII", raw[:16])
    except struct.error:
        w16 = h16 = fmt16 = cs16 = 0
    if fmt16 in _PIXEL_FORMATS and 0 < w16 < 20000 and 0 < h16 < 20000 and cs16 <= 32:
        mode, bpp = _PIXEL_FORMATS[fmt16]
        return (w16, h16, mode, bpp, 16)
    # 12-byte header (older Android).
    try:
        w12, h12, fmt12 = struct.unpack("<III", raw[:12])
    except struct.error:
        return None
    if fmt12 in _PIXEL_FORMATS and 0 < w12 < 20000 and 0 < h12 < 20000:
        mode, bpp = _PIXEL_FORMATS[fmt12]
        return (w12, h12, mode, bpp, 12)
    return None


def _looks_secure_frame(img) -> bool:
    """FLAG_SECURE screens come back as a solid-black bitmap. Sample
    a small ring of pixels; if the min/max spread is trivially small
    across the sampled channels, we're almost certainly looking at
    a censored frame."""
    try:
        w, h = img.size
        # Sample 25 evenly-distributed points inside the top/bottom margins.
        pts = []
        for fy in (0.15, 0.35, 0.55, 0.75):
            row = int(h * fy)
            for fx in (0.10, 0.30, 0.50, 0.70, 0.90):
                col = int(w * fx)
                pts.append(img.getpixel((col, row)))
    except Exception:
        return False
    values: list[int] = []
    for p in pts:
        if isinstance(p, tuple):
            values.extend(int(c) for c in p[:3])
        else:
            values.append(int(p))
    if not values:
        return False
    span = max(values) - min(values)
    # A real UI always has some visual variance. Threshold of 6 keeps
    # false positives to essentially zero — even a "solid grey" splash
    # screen has AA/dithering that pushes span above 10.
    return span < 6


def _capture_png(
    serial: str, *, max_width, max_size, quality: int, format: str,
) -> dict[str, Any]:
    """PNG-source fallback path. Same shape as the raw path once decoded."""
    started = time.monotonic()
    try:
        r = run(["exec-out", "screencap", "-p"], serial=serial, timeout=25,
                capture_binary=True)
    except AdbNotFoundError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"screencap failed: {e}"}
    capture_ms = int((time.monotonic() - started) * 1000)
    if r.returncode != 0:
        stderr = (r.stderr or b"").decode("utf-8", "replace").strip()
        return {"ok": False, "error": stderr or f"screencap exit {r.returncode}"}
    png = r.stdout or b""
    if not png or not png.startswith(b"\x89PNG"):
        return {"ok": False, "error": "screencap returned no PNG data",
                "size_bytes": len(png)}
    width, height = _png_dimensions(png)

    fmt = (format or "png").lower()
    if fmt == "png" and not max_size and not max_width:
        # Trivial happy path: caller wants native PNG, no downscale,
        # no re-encode. Ship the bytes straight through.
        return {
            "ok": True, "bytes": png, "mime": "image/png",
            "format": "png", "quality": None,
            "width": width, "height": height,
            "source_width": width, "source_height": height,
            "size_bytes": len(png), "downscaled": False,
            "capture_mode": "png", "capture_ms": capture_ms, "encode_ms": 0,
            "secure_frame": None,
        }

    try:
        from PIL import Image  # type: ignore
    except Exception:
        return {
            "ok": True, "bytes": png, "mime": "image/png",
            "format": "png", "quality": None,
            "width": width, "height": height,
            "source_width": width, "source_height": height,
            "size_bytes": len(png), "downscaled": False,
            "capture_mode": "png", "capture_ms": capture_ms, "encode_ms": 0,
            "secure_frame": None, "pil_missing": True,
        }
    try:
        img = Image.open(io.BytesIO(png))
        img.load()
    except Exception as e:
        return {"ok": False, "error": f"PNG parse failed: {e}",
                "capture_ms": capture_ms}
    secure = _looks_secure_frame(img)
    return _postprocess({
        "ok": True, "_pil_image": img,
        "source_width": width, "source_height": height,
        "capture_ms": capture_ms, "capture_mode": "png",
        "secure_frame": secure,
    }, max_width=max_width, max_size=max_size,
       quality=quality, format=format)


def _postprocess(
    partial: dict[str, Any], *,
    max_width, max_size, quality: int, format: str,
) -> dict[str, Any]:
    """Common downscale + re-encode stage for raw and PNG paths."""
    img = partial.pop("_pil_image")
    src_w = partial["source_width"]
    src_h = partial["source_height"]

    # Compute target dims (long-side cap wins over legacy width-cap).
    target_w, target_h = src_w, src_h
    if max_size and int(max_size) > 0:
        cap = int(max_size)
        long_side = max(src_w, src_h)
        if long_side > cap:
            ratio = cap / long_side
            target_w = max(1, int(round(src_w * ratio)))
            target_h = max(1, int(round(src_h * ratio)))
    elif max_width and int(max_width) > 0 and src_w > int(max_width):
        cap = int(max_width)
        target_w = cap
        target_h = max(1, int(src_h * (cap / src_w)))

    fmt = (format or "png").lower()
    started = time.monotonic()
    if (target_w, target_h) != (src_w, src_h):
        img = img.resize((target_w, target_h), Image.LANCZOS)
        downscaled = True
    else:
        downscaled = False

    buf = io.BytesIO()
    if fmt == "webp":
        img.save(buf, format="WEBP", quality=max(1, min(100, int(quality))), method=4)
        mime = "image/webp"
    elif fmt == "jpeg":
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        img.save(buf, format="JPEG",
                 quality=min(95, max(1, int(quality))),
                 subsampling=0, optimize=False, progressive=False)
        mime = "image/jpeg"
    else:
        # PNG path — no lossy quality knob, just compress at level 6.
        img.save(buf, format="PNG", optimize=False, compress_level=6)
        mime = "image/png"
    encode_ms = int((time.monotonic() - started) * 1000)

    partial.update({
        "bytes": buf.getvalue(),
        "mime": mime,
        "format": fmt if fmt in ("png", "jpeg", "webp") else "png",
        "quality": max(1, min(100, int(quality))) if fmt in ("jpeg", "webp") else None,
        "width": target_w,
        "height": target_h,
        "size_bytes": len(buf.getvalue()),
        "downscaled": downscaled,
        "encode_ms": encode_ms,
    })
    return partial


# Lazy import so the module still imports on hosts without Pillow.
try:
    from PIL import Image  # type: ignore  # noqa: E402
except Exception:
    Image = None  # type: ignore


def _png_dimensions(png: bytes) -> tuple[int, int]:
    if len(png) < 24 or not png.startswith(b"\x89PNG"):
        return (0, 0)
    try:
        width, height = struct.unpack(">II", png[16:24])
        return (int(width), int(height))
    except Exception:
        return (0, 0)


# Kept for backwards compat with tests that call the old _encode helper.
def _encode(img, buf, *, fmt: str, quality: int) -> None:
    q = max(1, min(100, int(quality)))
    if fmt == "jpeg":
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=min(95, q),
                 subsampling=0, optimize=False, progressive=False)
    elif fmt == "webp":
        img.save(buf, format="WEBP", quality=q, method=4)
    else:
        raise ValueError(f"unsupported encode format: {fmt!r}")

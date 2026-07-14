"""Device screenshot capture via `adb exec-out screencap -p`.

Returns raw PNG bytes plus optional downscale + JPEG/WebP re-encoding to
keep vision-agent payloads reasonable. Same UX contract as the desktop
screenshot handler.

v3.83.0 quality overhaul:
  * WebP output (`format=webp`) — same visual quality as JPEG at ~40%
    the size, or dramatically better quality at the same size. Supported
    when Pillow's WebP plugin is present (it is on the bridge).
  * `subsampling=0` for JPEG (4:4:4) instead of the default 4:2:0 —
    text on the phone screen no longer smears colour into the surrounding
    pixels, which was the main "artefacts in motion" complaint.
  * `optimize=False` for PNG downscale writes — the pixel-perfect PNG
    branch was spending ~200 ms on entropy coding for zero visible gain.
  * `max_width=0` (or omitted) now means "native resolution, no resize"
    so the Dashboard's "High-res" toggle can bypass Pillow entirely
    when the user wants the raw phone pixels.
"""
from __future__ import annotations

import io
from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run


def capture(
    serial: str,
    *,
    max_width: int | None = None,
    quality: int = 85,
    format: str = "png",
) -> dict[str, Any]:
    """Capture a screenshot from the device.

    * `max_width` — if truthy (>0), downscale so width <= max_width
      (preserves aspect ratio). Requires Pillow; when Pillow is not
      installed the original PNG is returned unchanged. Pass 0 or None
      to skip resizing entirely (native resolution).
    * `quality` — encoder quality (1-95 for JPEG, 1-100 for WebP).
      Ignored for PNG output.
    * `format` — "png" (default), "jpeg", or "webp". JPEG/WebP only take
      effect when Pillow is available.

    Returns:
      {"ok": bool, "bytes": bytes, "mime": str, "width": int, "height": int,
       "size_bytes": int, "downscaled": bool, "error": str | None,
       "format": str, "quality": int | None}
    """
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}

    # `exec-out` streams stdout unmodified. `adb shell screencap -p` on some
    # Android versions applies CRLF translation to stdout and corrupts the
    # PNG; exec-out avoids that. Available since ADB 1.0.32+.
    try:
        r = run(["exec-out", "screencap", "-p"], serial=serial, timeout=20, capture_binary=True)
    except AdbNotFoundError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"screencap failed: {e}"}

    if r.returncode != 0:
        stderr = (r.stderr or b"").decode("utf-8", "replace").strip()
        return {"ok": False, "error": stderr or f"screencap exit {r.returncode}"}

    png = r.stdout or b""
    if not png or not png.startswith(b"\x89PNG"):
        return {"ok": False, "error": "screencap returned no PNG data", "size_bytes": len(png)}

    width, height = _png_dimensions(png)
    # `source_*` = native device pixels in the *current* orientation
    # (screencap follows rotation, so a landscape phone gives us
    # 3200x1440 here even if `wm size` still reports 1440x3200). The
    # frontend uses these values — not the /info physical size — to
    # translate CSS clicks back to phone coords, so tap+swipe work
    # regardless of rotation.
    result: dict[str, Any] = {
        "ok": True,
        "bytes": png,
        "mime": "image/png",
        "format": "png",
        "quality": None,
        "width": width,
        "height": height,
        "source_width": width,
        "source_height": height,
        "size_bytes": len(png),
        "downscaled": False,
    }

    fmt = (format or "png").lower()
    needs_resize = bool(max_width) and width and int(max_width) > 0 and width > int(max_width)
    needs_recode = fmt in ("jpeg", "webp")
    if not (needs_resize or needs_recode):
        return result

    try:
        from PIL import Image  # type: ignore
    except Exception:
        result["pil_missing"] = True
        return result

    try:
        img = Image.open(io.BytesIO(png))
        if needs_resize:
            new_w = int(max_width)
            new_h = max(1, int(img.height * (new_w / img.width)))
            img = img.resize((new_w, new_h), Image.LANCZOS)
            result["width"] = img.width
            result["height"] = img.height
            result["downscaled"] = True

        if needs_recode:
            buf = io.BytesIO()
            _encode(img, buf, fmt=fmt, quality=quality)
            result["bytes"] = buf.getvalue()
            result["mime"] = f"image/{fmt}"
            result["format"] = fmt
            result["quality"] = max(1, min(100, int(quality)))
            result["size_bytes"] = len(result["bytes"])
        elif needs_resize:
            # PNG resize path: skip `optimize=True` (200 ms savings) —
            # the smaller image already compresses fine at the default
            # zlib level 6.
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=False, compress_level=6)
            result["bytes"] = buf.getvalue()
            result["size_bytes"] = len(result["bytes"])
    except Exception as e:
        result["postprocess_error"] = str(e)
    return result


def _encode(img, buf: io.BytesIO, *, fmt: str, quality: int) -> None:
    """Encode `img` into `buf` as JPEG or WebP using quality-oriented settings.

    JPEG uses subsampling=0 (4:4:4) so red/blue text on grey UI chrome
    doesn't smear — this was the main artefacts-in-motion complaint on
    the low-bandwidth 360px preview. WebP is method=4 (moderate compute
    for better quality/size tradeoff) with the same no-subsampling
    hint via `-jpeg-like` behaviour.
    """
    q = max(1, min(100, int(quality)))
    if fmt == "jpeg":
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(
            buf,
            format="JPEG",
            quality=min(95, q),
            subsampling=0,       # 4:4:4 — no chroma smearing on UI text
            optimize=False,      # optimize=True costs ~150ms for ~5% size
            progressive=False,
        )
    elif fmt == "webp":
        # WebP handles RGBA natively — no conversion needed.
        img.save(
            buf,
            format="WEBP",
            quality=q,
            method=4,            # 0 (fast) .. 6 (slowest, best ratio)
        )
    else:
        raise ValueError(f"unsupported encode format: {fmt!r}")


def _png_dimensions(png: bytes) -> tuple[int, int]:
    """Read width/height from the PNG IHDR chunk without decoding pixels."""
    if len(png) < 24 or not png.startswith(b"\x89PNG"):
        return (0, 0)
    # IHDR is always right after the 8-byte signature: 4-byte length,
    # 4-byte type, then 13-byte data (4 width, 4 height, ...).
    import struct
    try:
        width, height = struct.unpack(">II", png[16:24])
        return (int(width), int(height))
    except Exception:
        return (0, 0)

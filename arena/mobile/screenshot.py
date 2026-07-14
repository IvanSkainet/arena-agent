"""Device screenshot capture via `adb exec-out screencap -p`.

Returns raw PNG bytes plus optional downscale/JPEG re-encoding to keep
vision-agent payloads reasonable. Same UX contract as the desktop
screenshot handler.
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

    * `max_width` — if set, downscale so width <= max_width (preserves aspect
      ratio). Requires Pillow; when Pillow is not installed the original
      PNG is returned unchanged.
    * `quality` — JPEG encoder quality (1-95). Ignored for PNG output.
    * `format` — "png" (default) or "jpeg". JPEG only takes effect when
      Pillow is available.

    Returns:
      {"ok": bool, "bytes": bytes, "mime": str, "width": int, "height": int,
       "size_bytes": int, "downscaled": bool, "error": str | None}
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
    result: dict[str, Any] = {
        "ok": True,
        "bytes": png,
        "mime": "image/png",
        "width": width,
        "height": height,
        "size_bytes": len(png),
        "downscaled": False,
    }

    # Optional post-processing: downscale + JPEG re-encode. Pillow is a soft
    # dependency; if it's missing we return the raw PNG and note that.
    needs_resize = max_width is not None and width and width > max_width
    needs_recode = format.lower() == "jpeg"
    if needs_resize or needs_recode:
        try:
            from PIL import Image  # type: ignore
        except Exception:
            result["pil_missing"] = True
            return result
        try:
            img = Image.open(io.BytesIO(png))
            if needs_resize and img.width > max_width:
                new_w = int(max_width)
                new_h = max(1, int(img.height * (new_w / img.width)))
                img = img.resize((new_w, new_h), Image.LANCZOS)
                result["width"] = img.width
                result["height"] = img.height
                result["downscaled"] = True
            buf = io.BytesIO()
            if needs_recode:
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(buf, format="JPEG", quality=max(1, min(95, int(quality))))
                result["bytes"] = buf.getvalue()
                result["mime"] = "image/jpeg"
                result["size_bytes"] = len(result["bytes"])
            elif needs_resize:
                img.save(buf, format="PNG", optimize=True)
                result["bytes"] = buf.getvalue()
                result["size_bytes"] = len(result["bytes"])
        except Exception as e:
            result["postprocess_error"] = str(e)
    return result


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

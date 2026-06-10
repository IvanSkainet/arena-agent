"""Desktop screenshot capture and transform helpers."""
from __future__ import annotations

import os
import tempfile
from collections.abc import Awaitable, Callable
from typing import Any

DesktopExec = Callable[[str, float], Awaitable[dict[str, Any]]]
DetectEnv = Callable[[], dict[str, Any]]
AuditFn = Callable[[dict[str, Any]], None]


async def capture_desktop_screenshot(
    *,
    fmt: str = "base64",
    scale: float | None = None,
    max_width: int | None = None,
    quality: int = 80,
    desktop_exec: DesktopExec,
    detect_env: DetectEnv,
    audit_fn: AuditFn | None = None,
) -> dict[str, Any]:
    """Capture the desktop and optionally transform/re-encode the image.

    Returns `{ok: True, bytes, encoding, transformed, tool}` on success, or
    `{ok: False, error}` on failure. The caller decides whether to return JSON
    base64 or a binary HTTP response.
    """
    fmt = (fmt or "base64").lower()
    quality = max(1, min(100, int(quality or 80)))
    tmp_path = tempfile.mktemp(suffix=".png", prefix="arena_desktop_")
    env = detect_env()

    cmd = None
    if env.get("has_spectacle"):
        wayland_env = f'WAYLAND_DISPLAY={os.environ.get("WAYLAND_DISPLAY", "wayland-0")}'
        display_env = f'DISPLAY={os.environ.get("DISPLAY", ":0")}'
        cmd = f'{wayland_env} {display_env} spectacle -b -n -f -o {tmp_path}'
    elif env.get("has_grim") and env.get("wayland"):
        cmd = f'grim {tmp_path}'
    elif env.get("has_scrot") and env.get("x11"):
        cmd = f'DISPLAY={os.environ.get("DISPLAY", ":0")} scrot -o {tmp_path}'
    else:
        return {"ok": False, "error": "No screenshot tool available (need spectacle, grim, or scrot)"}

    result = await desktop_exec(cmd, timeout=15)
    if not result.get("ok") or not os.path.exists(tmp_path):
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return {"ok": False, "error": f"Screenshot failed: {result.get('stderr', result.get('error', 'unknown'))}"}

    try:
        with open(tmp_path, "rb") as f:
            img_bytes = f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not img_bytes:
        return {"ok": False, "error": "Screenshot file is empty"}

    tool = "spectacle" if env.get("has_spectacle") else ("grim" if env.get("has_grim") else "scrot")
    out_format = "png"
    transformed = False

    if fmt in ("jpeg", "jpg", "webp") or scale or max_width:
        try:
            from PIL import Image as _PILImage
            import io as _io

            im = _PILImage.open(_io.BytesIO(img_bytes))
            w, h = im.size
            target_w = w
            if scale and 0 < scale <= 1:
                target_w = int(w * scale)
            if max_width and max_width > 0:
                target_w = min(target_w, max_width)
            if target_w != w and target_w > 0:
                target_h = max(1, int(h * (target_w / w)))
                im = im.resize((target_w, target_h), _PILImage.LANCZOS)
            buf = _io.BytesIO()
            if fmt in ("jpeg", "jpg"):
                im.convert("RGB").save(buf, format="JPEG", quality=quality)
                out_format = "jpeg"
            elif fmt == "webp":
                im.save(buf, format="WEBP", quality=quality)
                out_format = "webp"
            else:
                im.save(buf, format="PNG", optimize=True)
                out_format = "png"
            img_bytes = buf.getvalue()
            transformed = True
        except Exception as exc:
            if audit_fn:
                audit_fn({"type": "screenshot_transform_failed", "error": str(exc)})
            out_format = "png"

    return {
        "ok": True,
        "bytes": img_bytes,
        "encoding": out_format,
        "transformed": transformed,
        "tool": tool,
    }

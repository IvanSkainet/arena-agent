"""Image preprocessing for OCR/document scenarios (v4.87.0).

This is a generic file-in/file-out capability used by both `image.*` MCP
tools and `ocr.extract(preprocess=true)`. Pillow is the baseline runtime;
OpenCV is optional and used only for deskew when available.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": msg}
    out.update(extra)
    return out


def _pillow_info() -> dict[str, Any]:
    try:
        import PIL
        from PIL import Image  # noqa: F401
        return {"ok": True, "version": getattr(PIL, "__version__", None)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _opencv_info() -> dict[str, Any]:
    try:
        import cv2
        return {"ok": True, "version": getattr(cv2, "__version__", None)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def image_health() -> dict[str, Any]:
    pillow = _pillow_info()
    opencv = _opencv_info()
    return {
        "ok": bool(pillow.get("ok")),
        "pillow": pillow,
        "opencv": opencv,
        "ffmpeg": shutil.which("ffmpeg"),
        "notes": "Pillow is required; OpenCV is optional and enables deskew.",
    }


def output_dir() -> Path:
    root = Path(os.environ.get("ARENA_IMAGE_DIR")
                or (Path.home() / ".arena" / "ocr-preprocessed")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def default_output_path(src: Path) -> Path:
    stem = src.stem[:80] or "image"
    return output_dir() / f"{stem}.ocr-{int(time.time() * 1000)}.png"


def _resize_max(img, max_size: int | None, steps: list[str]):
    if not max_size or max_size <= 0:
        return img
    w, h = img.size
    long_side = max(w, h)
    if long_side <= max_size:
        return img
    scale = max_size / float(long_side)
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    steps.append(f"resize:{w}x{h}->{new_size[0]}x{new_size[1]}")
    return img.resize(new_size)


def _threshold(img, value: int, steps: list[str]):
    value = max(0, min(255, int(value)))
    steps.append(f"threshold:{value}")
    return img.point(lambda p: 255 if p > value else 0)


def _deskew_pillow(img, steps: list[str]):
    try:
        import cv2
        import numpy as np
    except Exception as e:
        steps.append(f"deskew:skipped:{type(e).__name__}")
        return img
    arr = np.array(img)
    if arr.ndim == 3:
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    else:
        gray = arr
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if coords.size == 0:
        steps.append("deskew:skipped:no-text")
        return img
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.2 or abs(angle) > 20:
        steps.append(f"deskew:skipped:angle={angle:.2f}")
        return img
    steps.append(f"deskew:{angle:.2f}")
    return img.rotate(angle, expand=True, fillcolor=255)


def preprocess_for_ocr(
    file: str | Path,
    *,
    output: str | Path | None = None,
    max_size: int | None = 2200,
    grayscale: bool = True,
    autocontrast: bool = True,
    threshold: bool = False,
    threshold_value: int = 170,
    deskew: bool = False,
) -> dict[str, Any]:
    health = image_health()
    if not health.get("pillow", {}).get("ok"):
        return _err("Pillow is not available", health=health)
    from PIL import Image, ImageOps

    src = Path(file).expanduser()
    if not src.exists():
        return _err(f"file not found: {src}")
    if not src.is_file():
        return _err(f"not a file: {src}")
    out = Path(output).expanduser() if output else default_output_path(src)
    out.parent.mkdir(parents=True, exist_ok=True)
    steps: list[str] = []

    try:
        img = Image.open(src)
        img.load()
    except Exception as e:
        return _err(f"cannot open image: {type(e).__name__}: {e}")
    in_size = img.size
    if grayscale:
        img = ImageOps.grayscale(img)
        steps.append("grayscale")
    img = _resize_max(img, max_size, steps)
    if autocontrast:
        img = ImageOps.autocontrast(img)
        steps.append("autocontrast")
    if deskew:
        img = _deskew_pillow(img, steps)
    if threshold:
        img = _threshold(img, threshold_value, steps)
    try:
        img.save(out, format="PNG")
    except Exception as e:
        return _err(f"cannot save output: {type(e).__name__}: {e}")
    return {
        "ok": True,
        "input": str(src),
        "output": str(out),
        "input_width": in_size[0],
        "input_height": in_size[1],
        "width": img.size[0],
        "height": img.size[1],
        "steps": steps,
        "size_bytes": out.stat().st_size,
    }


__all__ = ["image_health", "preprocess_for_ocr", "default_output_path", "output_dir"]

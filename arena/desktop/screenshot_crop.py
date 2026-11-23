"""Crop a captured picture to a desktop region and say which rectangle was kept."""
from __future__ import annotations

from typing import Any

# The arithmetic is the long-standing one: a negative origin moves to 0 and the
# far edges stop at the picture, so the kept area can be smaller than the
# region or sit somewhere else. It is computed apart from the crop itself so
# the answer can say which desktop area the picture really shows.


def kept_box(size: tuple[int, int], region: dict[str, int]) -> tuple[int, int, int, int]:
    """Return the part of ``region`` a crop keeps, as (left, top, right, bottom)."""
    left = max(0, region["x"])
    top = max(0, region["y"])
    right = min(size[0], left + max(1, region["width"]))
    bottom = min(size[1], top + max(1, region["height"]))
    return left, top, right, bottom


def crop_kept(im: Any, region: dict[str, int] | None) -> tuple[Any, dict[str, int] | None]:
    """Crop ``im`` to ``region`` and return it with the rectangle that was kept; no region, no crop."""
    if not region:
        return im, None
    left, top, right, bottom = kept_box(im.size, region)
    return im.crop((left, top, right, bottom)), {"x": left, "y": top, "width": right - left, "height": bottom - top}


__all__ = ["crop_kept", "kept_box"]

"""Derive a posture's honest preset identity from its effective axes."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def derive_preset_name(
    posture: Mapping[str, Any],
    presets: Mapping[str, Mapping[str, str]],
    axes: Sequence[str],
) -> str:
    """Return the exact matching preset name, otherwise ``custom``.

    Persisted labels are deliberately ignored: only the effective axis tuple is
    security-relevant.  If configuration drift creates duplicate definitions,
    ambiguity is reported as custom rather than selecting by dictionary order.
    """
    matches = [
        name
        for name, definition in presets.items()
        if all(posture.get(axis) == definition.get(axis) for axis in axes)
    ]
    return matches[0] if len(matches) == 1 else "custom"


__all__ = ["derive_preset_name"]

"""Shape-checked ``json.loads`` wrappers.

``json.loads`` returns whatever the document happens to contain. A file
holding the four bytes ``null`` is *valid* JSON, and so are ``5`` and
``"x"``. Functions annotated ``-> dict[str, Any]`` that end in
``return json.loads(...)`` therefore lie: the annotation says "mapping",
the runtime hands the caller ``None``, and the crash lands one or two
frames away from the file that caused it (``'NoneType' object has no
attribute 'get'``), pointing at innocent code.

This was live in ``arena.resources.mission_catalog.load_mission_json``:
a ``mission.json`` containing ``null`` -- an interrupted write, a synced
placeholder -- took down the whole mission listing, not just that one
mission.

These helpers keep the annotation honest. The parse still raises on
malformed JSON (callers already handle that); only the *shape* is
normalised, and only when the caller says which shape it needs.
"""
from __future__ import annotations

import json
from typing import Any


def loads_object(raw: str | bytes | bytearray, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse ``raw`` and return a dict, substituting ``default`` for any other shape.

    Raises ``json.JSONDecodeError`` for malformed input, exactly like
    ``json.loads``. A valid non-object document (``null``, ``5``,
    ``[1]``) is not an error here -- it is simply not the shape the
    caller declared, so ``default`` (``{}`` unless given) is returned.
    """
    value = json.loads(raw)
    if isinstance(value, dict):
        return value
    return dict(default) if default else {}


def loads_array(raw: str | bytes | bytearray, *, default: list[Any] | None = None) -> list[Any]:
    """Parse ``raw`` and return a list, substituting ``default`` for any other shape."""
    value = json.loads(raw)
    if isinstance(value, list):
        return value
    return list(default) if default else []


def as_object(value: Any, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    """Coerce an already-parsed value to a dict without re-parsing."""
    if isinstance(value, dict):
        return value
    return dict(default) if default else {}


__all__ = ["as_object", "loads_array", "loads_object"]

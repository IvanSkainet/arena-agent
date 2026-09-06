"""Strict request-field contracts shared by plan/react/reflect endpoints."""
from __future__ import annotations

from typing import Any

from arena.handler_errors import BodyFieldError


class CognitiveInputError(ValueError):
    """A cognitive endpoint request has an unusable field shape."""


def require_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CognitiveInputError("JSON body must be an object")
    return value


def reject_unknown(data: dict[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise CognitiveInputError("unexpected field(s): " + ", ".join(unknown))


def required_text(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise CognitiveInputError(f"missing {field}")
    if not isinstance(value, str):
        raise CognitiveInputError(f"{field} must be a string")
    return value.strip()


def optional_text(data: dict[str, Any], field: str) -> str:
    value = data.get(field, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CognitiveInputError(f"{field} must be a string")
    return value


def optional_string_list(data: dict[str, Any], field: str) -> list[str]:
    value = data.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CognitiveInputError(f"{field} must be a list of strings")
    return list(value)


def optional_object(data: dict[str, Any], field: str) -> dict[str, Any]:
    value = data.get(field, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CognitiveInputError(f"{field} must be an object")
    return dict(value)


def positive_int(data: dict[str, Any], field: str, default: int) -> int:
    """A count the caller supplied, refused as a named field if it is not one.

    Raises `BodyFieldError` rather than the local `CognitiveInputError` so
    that the refusal carries `field` and `received` like every other body
    rejection since #270 -- the document promises those keys for any
    operation with a numeric body field, and /v1/plan and /v1/react are two
    of them. `BodyFieldError` is a ValueError, so the handlers that already
    catch `CognitiveInputError` (also a ValueError) keep working either way.
    """
    value = data.get(field, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise BodyFieldError(field, value)
    if value < 1:
        raise BodyFieldError(field, value, expected="an integer no smaller than 1")
    return value

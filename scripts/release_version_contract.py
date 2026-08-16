"""Strict, non-interchangeable source-version and published-tag contracts."""
from __future__ import annotations

import re

_VERSION_PATTERN = r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
_SOURCE_VERSION_RE = re.compile(rf"^{_VERSION_PATTERN}$")
_RELEASE_TAG_RE = re.compile(rf"^v{_VERSION_PATTERN}$")


def _matched_parts(match: re.Match[str] | None) -> tuple[int, ...]:
    return tuple(int(field) for field in match.groups()) if match is not None else ()


def source_parts(version: str) -> tuple[int, ...]:
    """Parse the source-only `X.Y.Z` contract; a `v` prefix is invalid."""
    return _matched_parts(_SOURCE_VERSION_RE.fullmatch(version))


def release_tag_parts(tag: str) -> tuple[int, ...]:
    """Parse the published-only `vX.Y.Z` contract; the prefix is mandatory."""
    return _matched_parts(_RELEASE_TAG_RE.fullmatch(tag))


__all__ = ["release_tag_parts", "source_parts"]

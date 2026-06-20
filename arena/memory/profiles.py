"""Memory profile helpers."""
from __future__ import annotations

DEFAULT_MEMORY_PROFILE = "default"
ALL_MEMORY_PROFILES = "*"


def normalize_memory_profile(profile: str | None) -> str:
    value = str(profile or DEFAULT_MEMORY_PROFILE).strip()
    return value or DEFAULT_MEMORY_PROFILE


def normalize_memory_profile_filter(profile: str | None) -> str | None:
    value = str(profile or "").strip()
    if not value:
        return DEFAULT_MEMORY_PROFILE
    if value in {ALL_MEMORY_PROFILES, "all", "ALL"}:
        return None
    return normalize_memory_profile(value)


def validate_memory_profile(profile: str | None, *, allow_all: bool = False) -> str | None:
    value = str(profile or "").strip()
    if not value:
        return None
    if allow_all and value in {ALL_MEMORY_PROFILES, "all", "ALL"}:
        return None
    norm = normalize_memory_profile(value)
    if len(norm) > 120:
        return "profile is too long (max 120 chars)"
    if norm.startswith("/") or norm.endswith("/") or "//" in norm:
        return "profile must not start/end with '/' or contain '//'"
    if any(ch in norm for ch in ("\x00", "\n", "\r", "\t")):
        return "profile contains forbidden control characters"
    return None

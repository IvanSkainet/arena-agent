"""Shared helpers for browser session profile handlers."""
from __future__ import annotations

import re
from pathlib import Path

from arena.constants import APP_DIR

PROFILES_DIR = APP_DIR / "profiles"


def ensure_profiles_dir() -> Path:
    """Ensure profiles directory exists."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILES_DIR


def sanitize_profile_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-.]", "_", name)


def auth_and_record(ctx, request):
    response = ctx.require_auth(request)
    if response:
        return response
    ctx.record_request()
    return None

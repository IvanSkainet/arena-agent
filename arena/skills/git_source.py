"""Fail-closed source policy for third-party skills cloned with Git."""
from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlparse

from arena.security_ssrf import _validate_url

_ALLOWED_GIT_SCHEMES = frozenset({"http", "https"})


def validate_git_source_url(url: str) -> str | None:
    """Return an error unless *url* is a credential-free public HTTP(S) URL."""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except (TypeError, ValueError):
        return "invalid git source URL"
    if parsed.scheme not in _ALLOWED_GIT_SCHEMES:
        return "git source scheme not allowed (only http/https)"
    if not parsed.hostname:
        return "git source host is required"
    if parsed.username is not None or parsed.password is not None:
        return "credentials in git source URL are not allowed"
    authority = parsed.netloc
    # urllib already rejects values above 65535 while reading ``parsed.port``.
    if port == 0 or authority.endswith(":"):
        return "git source port is invalid"
    error = _validate_url(url)
    return f"git source rejected: {error}" if error else None


def git_protocol_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """Copy non-Git environment values and install an isolated Git policy."""
    result = {
        key: value
        for key, value in environ.items()
        if not key.upper().startswith("GIT_")
    }
    result.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ALLOW_PROTOCOL": "https:http",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_TERMINAL_PROMPT": "0",
    })
    return result

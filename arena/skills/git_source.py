"""Fail-closed source policy for third-party skills cloned with Git."""
from __future__ import annotations

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
    # urllib already rejects values above 65535 while reading ``parsed.port``;
    # zero is the only remaining integer outside the TCP port range.
    if port == 0:
        return "git source port is invalid"
    error = _validate_url(url)
    return f"git source rejected: {error}" if error else None


def git_protocol_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """Copy the process environment while pinning Git's transport allowlist."""
    result = {
        key: value
        for key, value in environ.items()
        if key != "GIT_CONFIG_COUNT"
        and not key.startswith("GIT_CONFIG_KEY_")
        and not key.startswith("GIT_CONFIG_VALUE_")
    }
    result["GIT_ALLOW_PROTOCOL"] = "https:http"
    result["GIT_PROTOCOL_FROM_USER"] = "0"
    return result

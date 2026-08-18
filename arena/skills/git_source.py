"""Fail-closed source policy for third-party skills cloned with Git."""
from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from arena.security_http import _public_addresses
from arena.security_ssrf import _coerce_ip

_ALLOWED_GIT_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class ResolvedGitSource:
    """One Git URL and the exact public peers accepted for its connection."""

    url: str
    host: str
    port: int
    addresses: tuple[str, ...]

    def curl_resolve_values(self) -> tuple[str, ...]:
        if _coerce_ip(self.host) is not None:
            return ()
        return tuple(
            f"{self.host}:{self.port}:"
            f"{'[' + address + ']' if ':' in address else address}"
            for address in self.addresses
        )


def validate_git_source_url(url: str) -> str | None:
    """Validate the static credential-free HTTP(S) Git URL contract."""
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
    # urllib already rejects values above 65535 while reading ``parsed.port``.
    if port == 0 or parsed.netloc.endswith(":"):
        return "git source port is invalid"
    return None


def resolve_git_source_url(
    url: str,
) -> tuple[ResolvedGitSource | None, str | None]:
    """Resolve once and return the public peers Git must connect to."""
    static_error = validate_git_source_url(url)
    if static_error:
        return None, static_error
    try:
        parsed, host, addresses = _public_addresses(url)
    except OSError as exc:
        return None, f"git source rejected: {exc}"
    explicit_port = parsed.port
    port = explicit_port or (443 if parsed.scheme == "https" else 80)
    authority = f"[{host}]" if ":" in host else host
    if explicit_port is not None:
        authority = f"{authority}:{explicit_port}"
    normalized_url = parsed._replace(
        scheme=parsed.scheme.lower(), netloc=authority
    ).geturl()
    return ResolvedGitSource(
        url=normalized_url,
        host=host,
        port=port,
        addresses=addresses,
    ), None


def remove_tree_readonly(path: Path) -> bool:
    """Remove a tree, clearing Windows read-only bits when deletion refuses."""
    if not path.exists():
        return True

    def make_writable_then_retry(function, value, _exc_info):  # type: ignore[no-untyped-def]
        os.chmod(value, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
        function(value)

    try:
        shutil.rmtree(path, onerror=make_writable_then_retry)
    except OSError:
        return False
    return not path.exists()


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

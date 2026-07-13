"""Cloudflared tunnel admin regressions.

Cross-platform contract tests. Do not assume any specific machine layout.
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.admin.cloudflared import (
    _get_cloudflared_version,
    _get_update_hint,
    _resolve_cloudflared_with_source,
    _system_candidates,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_resolve_cloudflared_contract():
    """_resolve_cloudflared_with_source returns (path|None, source)."""
    cf_path, source = _resolve_cloudflared_with_source(REPO_ROOT)
    assert source in ("system", "bundled", "not_found")
    if source == "not_found":
        assert cf_path is None
    else:
        assert cf_path is not None
        assert "cloudflared" in cf_path.lower()


def test_get_cloudflared_version_returns_str_or_none():
    cf_path, _ = _resolve_cloudflared_with_source(REPO_ROOT)
    if cf_path:
        version = _get_cloudflared_version(cf_path)
        if version is not None:
            assert isinstance(version, str)
            assert "." in version


def test_system_candidates_present_for_every_platform():
    """Every OS has at least one well-known install path."""
    assert _system_candidates(), "system candidates must not be empty"


def test_update_hint_system_linux():
    hint = _get_update_hint("system", "2026.7.1")
    # Depending on host OS, hint content changes.
    system = platform.system()
    if system == "Linux":
        assert "package manager" in hint.lower() or "pacman" in hint.lower() or "apt" in hint.lower()
    elif system == "Darwin":
        assert "brew" in hint.lower()
    elif system == "Windows":
        assert "winget" in hint.lower() or "scoop" in hint.lower() or "download" in hint.lower()


def test_update_hint_bundled_mentions_arena():
    hint = _get_update_hint("bundled", "2026.7.1")
    assert "arena" in hint.lower() or "bundled" in hint.lower()


def test_update_hint_not_found_offers_install_command():
    """The install hint must give a copy-pasteable command, not just docs."""
    hint = _get_update_hint("not_found", None)
    lower = hint.lower()
    assert "install" in lower
    # Any of the supported install verbs should be mentioned.
    assert any(verb in lower for verb in ("winget", "scoop", "brew", "apt", "pacman"))


def test_update_hint_covers_all_sources():
    """Every documented source produces a non-empty, distinct hint."""
    hints = {source: _get_update_hint(source, "1.0") for source in ("system", "bundled", "not_found")}
    for source, hint in hints.items():
        assert hint and isinstance(hint, str), f"empty hint for source={source}"
    # And they are not accidentally identical.
    assert len(set(hints.values())) == 3

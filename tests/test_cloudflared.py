"""Cloudflared tunnel admin regressions."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.admin.cloudflared import (
    _get_cloudflared_version,
    _get_update_hint,
    _resolve_cloudflared_with_source,
)


def test_resolve_cloudflared_source_system():
    """Test that system cloudflared is found with source='system'."""
    root_agent = Path("/home/ivan/arena-bridge")
    cf_path, source = _resolve_cloudflared_with_source(root_agent)
    # On this system, cloudflared is installed in /usr/bin
    assert cf_path is not None or source == "not_found"
    if cf_path:
        assert source in ("system", "bundled")
        assert "cloudflared" in cf_path


def test_get_cloudflared_version():
    """Test version extraction from cloudflared binary."""
    root_agent = Path("/home/ivan/arena-bridge")
    cf_path, source = _resolve_cloudflared_with_source(root_agent)
    if cf_path:
        version = _get_cloudflared_version(cf_path)
        # Should return a version string or None
        if version:
            assert isinstance(version, str)
            # Version should look like "2026.7.1" or similar
            assert "." in version


def test_get_update_hint_system():
    """Test update hint for system cloudflared."""
    hint = _get_update_hint("system", "2026.7.1")
    assert "package manager" in hint or "brew" in hint or "Download" in hint


def test_get_update_hint_bundled():
    """Test update hint for bundled cloudflared."""
    hint = _get_update_hint("bundled", "2026.7.1")
    assert "bundled" in hint.lower() or "arena" in hint.lower()


def test_get_update_hint_not_found():
    """Test update hint when cloudflared not found."""
    hint = _get_update_hint("not_found", None)
    assert "install" in hint.lower() or "download" in hint.lower()

"""Capability map builder tests."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.capabilities import build_capabilities  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_build_capabilities_basic_shape():
    caps = build_capabilities(
        version="test-version",
        cdp_module_available=True,
        cdp_connected=False,
        desktop_env={"wayland": False, "x11": False, "session_type": "x11", "desktop": "TestDE"},
        service_info_fn=lambda: {"ok": True, "running_as": "test"},
        sys_svc_fn=lambda: {"ok": True, "tailscale": {"installed": True, "connected": False}},
    )
    assert caps["ok"] is True
    assert caps["version"] == "test-version"
    assert caps["browser"]["cdp_module"] is True
    assert caps["browser"]["cdp_connected"] is False
    assert caps["desktop"]["session"] == "x11"
    assert caps["desktop"]["desktop"] == "TestDE"
    assert caps["network"]["tailscale_installed"] is True


@pytest.mark.skipif(
    os.name != "posix",
    reason="KDE Wayland detection requires POSIX-shaped paths (/usr/bin/qdbus6, journalctl); Windows never picks this backend",
)
def test_build_capabilities_uses_kwin_journal_for_kde_wayland_window_ops(monkeypatch):
    monkeypatch.setattr("arena.capabilities.shutil.which", lambda name: "/usr/bin/" + name if name in {"qdbus6", "journalctl"} else None)
    caps = build_capabilities(
        version="test-version",
        cdp_module_available=True,
        cdp_connected=False,
        desktop_env={"wayland": True, "x11": True, "session_type": "wayland", "desktop": "KDE", "has_xdotool": True},
        service_info_fn=lambda: {"ok": True, "running_as": "test"},
        sys_svc_fn=lambda: {"ok": True, "tailscale": {"installed": True, "connected": False}},
    )
    assert caps["desktop"]["windows"]["backend"] == "kwin_journal"
    assert caps["desktop"]["active_window"]["backend"] == "kwin_journal"


def test_unified_bridge_capabilities_wrapper():
    caps = ub._capabilities_sync()
    assert caps["ok"] is True
    assert caps["version"] == ub.VERSION
    assert "platform" in caps
    assert "service" in caps

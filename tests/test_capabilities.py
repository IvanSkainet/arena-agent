"""Capability map builder tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.capabilities import build_capabilities  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_build_capabilities_basic_shape():
    caps = build_capabilities(
        version="test-version",
        cdp_module_available=True,
        cdp_connected=False,
        desktop_env={"wayland": False, "x11": False},
        service_info_fn=lambda: {"ok": True, "running_as": "test"},
        sys_svc_fn=lambda: {"ok": True, "tailscale": {"installed": True, "connected": False}},
    )
    assert caps["ok"] is True
    assert caps["version"] == "test-version"
    assert caps["browser"]["cdp_module"] is True
    assert caps["browser"]["cdp_connected"] is False
    assert "desktop" in caps
    assert caps["network"]["tailscale_installed"] is True


def test_unified_bridge_capabilities_wrapper():
    caps = ub._capabilities_sync()
    assert caps["ok"] is True
    assert caps["version"] == ub.VERSION
    assert "platform" in caps
    assert "service" in caps

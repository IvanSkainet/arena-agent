"""Desktop runtime helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.desktop.runtime as dr  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_desktop_helpers_reexported():
    assert ub._desktop_exec is dr._desktop_exec
    assert ub._detect_desktop_env is dr._detect_desktop_env
    assert ub._kwin_windows_via_script is dr._kwin_windows_via_script
    assert ub._get_active_window is dr._get_active_window


def test_detect_desktop_env_shape():
    env = dr._detect_desktop_env()
    for key in ["session_type", "wayland", "x11", "has_xdotool", "has_spectacle"]:
        assert key in env

"""Desktop screenshot helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.desktop.screenshot import capture_desktop_screenshot  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_unified_bridge_reexports_screenshot_helper():
    assert ub.capture_desktop_screenshot is capture_desktop_screenshot


async def _fake_exec(cmd: str, timeout: float = 10):
    return {"ok": False, "stderr": "nope"}


def test_capture_no_tool_shape():
    import asyncio
    res = asyncio.run(capture_desktop_screenshot(
        desktop_exec=_fake_exec,
        detect_env=lambda: {"has_spectacle": False, "has_grim": False, "has_scrot": False, "wayland": False, "x11": False},
    ))
    assert res["ok"] is False
    assert "No screenshot tool" in res["error"]

"""Desktop focus helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.desktop.focus import focus_window  # noqa: E402
import unified_bridge as ub  # noqa: E402


async def _exec_ok(cmd: str, timeout: float = 10):
    return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}


async def _active_none():
    return None


def test_unified_bridge_reexports_focus_helper():
    assert ub.focus_window is focus_window


def test_focus_missing_window_shape():
    import asyncio
    res = asyncio.run(focus_window(
        title_contains="missing",
        desktop_exec=lambda cmd, timeout=10: _exec_ok(cmd, timeout),
        detect_env=lambda: {"has_xdotool": False, "session_type": "test"},
        get_active_window=_active_none,
    ))
    assert res["ok"] is False
    assert res["error"] == "window_not_found"
    assert res["status"] == 404

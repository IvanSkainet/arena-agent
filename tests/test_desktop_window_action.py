"""Desktop window-action helper and handler regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.desktop.kwin_window_action import kwin_window_action_via_script  # noqa: E402
from arena.desktop.window_action import perform_window_action  # noqa: E402
from arena.desktop.window_action_handler import make_desktop_window_action_handler  # noqa: E402
from arena.handler_context import DesktopHandlerContext  # noqa: E402
from arena.mcp.tool_desktop import handle_desktop_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
import unified_bridge as ub  # noqa: E402


async def _active_window():
    return {"id": "{editor}", "title": "Code - repo", "backend": "kwin_journal"}


async def _kwin_list_before():
    return {"ok": True, "backend": "kwin_journal", "count": 1, "windows": [{"id": "{editor}", "internal_id": "{editor}", "title": "Code - repo", "pid": 222, "resource_class": "code", "resource_name": "code", "desktop_file": "code", "active": True, "geometry": {"x": 100, "y": 100, "width": 900, "height": 700}}]}


async def _kwin_list_after():
    return {"ok": True, "backend": "kwin_journal", "count": 1, "windows": [{"id": "{editor}", "internal_id": "{editor}", "title": "Code - repo", "pid": 222, "resource_class": "code", "resource_name": "code", "desktop_file": "code", "active": True, "geometry": {"x": 300, "y": 200, "width": 800, "height": 600}}]}


async def _exec(cmd: str, timeout: float = 10):
    if "activeOutputName" in cmd:
        return {"ok": True, "stdout": "DP-1\n", "stderr": ""}
    if "kscreen-doctor -o" in cmd:
        return {"ok": True, "stdout": "Output: 1 DP-1 uuid-1\n\tenabled\n\tconnected\n\tGeometry: 0,0 2560x1440\n", "stderr": ""}
    if "journalctl" in cmd:
        return {"ok": True, "stdout": 'ARENA_KWIN_ACTION_token {"ok": true, "action": "minimize", "target_id": "{editor}", "geometry": {"x": 1, "y": 2, "width": 3, "height": 4}, "minimized": true, "full_screen": false}\n', "stderr": ""}
    return {"ok": True, "stdout": "", "stderr": "", "exit_code": 0}



def test_perform_window_action_move_resize_via_kwin(monkeypatch):
    import arena.desktop.window_action as wa

    calls = {"n": 0}

    async def _list_windows(**kwargs):
        calls["n"] += 1
        return await (_kwin_list_before() if calls["n"] == 1 else _kwin_list_after())

    async def _kwin_action(action, target_id, **kwargs):
        assert action == "move_resize"
        assert target_id == "{editor}"
        return {"ok": True, "backend": "kwin_window_action"}

    monkeypatch.setattr(wa, "list_desktop_windows", _list_windows)
    monkeypatch.setattr(wa, "kwin_window_action_via_script", _kwin_action)
    result = asyncio.run(perform_window_action("move_resize", target_id="{editor}", x=300, y=200, width=800, height=600, desktop_exec=_exec, detect_env=lambda: {"session_type": "wayland", "has_xdotool": False}, kwin_windows_via_script=_kwin_list_before))
    assert result["ok"] is True
    assert result["tool"] == "kwin_window_action"
    assert result["verified"] is True
    assert result["after"]["geometry"]["width"] == 800



def test_kwin_window_action_script_accepts_loadscript_zero(monkeypatch):
    import arena.desktop.kwin_window_action as kwa

    monkeypatch.setattr(kwa.shutil, "which", lambda name: "/usr/bin/" + name if name in {"qdbus6", "journalctl"} else None)
    monkeypatch.setattr(kwa.uuid, "uuid4", lambda: type("U", (), {"hex": "token"})())
    result = asyncio.run(kwin_window_action_via_script("minimize", "{editor}", desktop_exec=_exec))
    assert result["ok"] is True
    assert result["minimized"] is True
    assert result.get("error") is None



def test_window_action_handler_dry_run_and_registry():
    async def _kwin_list():
        return await _kwin_list_before()

    ctx = DesktopHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        control_check=lambda: None,
        control_record_agent_action=lambda: None,
        desktop_exec=_exec,
        detect_desktop_env=lambda: {"session_type": "wayland", "has_xdotool": False},
        get_active_window=_active_window,
        kwin_windows_via_script=_kwin_list,
        capture_screenshot=ub.capture_desktop_screenshot,
        ocr_desktop=ub.ocr_desktop,
        kwin_focus_window=lambda *args, **kwargs: {"ok": True, "backend": "kwin_focus_script"},
        focus_window=ub.focus_window,
        audit=lambda event: None,
    )
    handler = make_desktop_window_action_handler(ctx)
    req = make_mocked_request("POST", "/v1/desktop/window_action", headers={"Authorization": "Bearer t"})

    async def _json():
        return {"action": "minimize", "class": "code", "dry_run": True}

    req.json = _json
    resp = asyncio.run(handler(req))
    data = json.loads(resp.text)
    assert data["ok"] is True
    assert data["dry_run"] is True
    assert data["target"]["title"] == "Code - repo"

    names = [tool["name"] for tool in MCP_TOOLS]
    assert "desktop.window_action" in names
    ctx2 = type("Ctx", (), {"app_config": staticmethod(lambda: {"port": 8765, "token": "t"})})()
    assert handle_desktop_tool("not-desktop", {}, ctx=ctx2) is None

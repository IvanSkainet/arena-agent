"""High-level OCR-to-action workflow regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.desktop.text_action import run_text_action  # noqa: E402
from arena.desktop.text_action_handler import make_desktop_text_action_handler  # noqa: E402
from arena.handler_context import DesktopHandlerContext  # noqa: E402
from arena.mcp.tool_desktop import handle_desktop_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
import unified_bridge as ub  # noqa: E402


async def _resolve(**kwargs):
    return {
        "ok": True,
        "query": kwargs.get("query"),
        "best_match": {"text": "Arena", "bbox": {"x": 120, "y": 140, "width": 70, "height": 20}, "center": {"x": 155, "y": 150}},
        "target_window": {"id": "{win}", "title": "Arena Page", "geometry": {"x": 0, "y": 0, "width": 900, "height": 700}, "display": {"name": "DP-1", "id": "DP-1"}},
        "window_candidates": [{"id": "{win}", "title": "Arena Page"}],
        "matches": [{"text": "Arena", "bbox": {"x": 120, "y": 140, "width": 70, "height": 20}, "center": {"x": 155, "y": 150}}],
        "displays": [{"name": "DP-1", "id": "DP-1", "geometry": {"x": 0, "y": 0, "width": 2560, "height": 1440}, "active": True}],
    }


async def _focus(**kwargs):
    return {"ok": True, "tool": "kwin_focus_script", "target_id": kwargs.get("window_id")}


async def _action(*args, **kwargs):
    return {"ok": True, "action": args[0], "target_id": kwargs.get("target_id"), "planned_geometry": {"x": 0, "y": 0, "width": 100, "height": 100}}


async def _exec(cmd: str, timeout: float = 10):
    return {"ok": True, "stdout": "", "stderr": "", "exit_code": 0}



def _ctx():
    return DesktopHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        control_check=lambda: None,
        control_record_agent_action=lambda: None,
        desktop_exec=_exec,
        detect_desktop_env=lambda: {"session_type": "wayland", "has_xdotool": False},
        get_active_window=lambda: None,
        kwin_windows_via_script=lambda: None,
        capture_screenshot=ub.capture_desktop_screenshot,
        ocr_desktop=ub.ocr_desktop,
        kwin_focus_window=lambda *args, **kwargs: {"ok": True},
        focus_window=ub.focus_window,
        audit=lambda event: None,
    )



def test_run_text_action_focus_and_window_action(monkeypatch):
    import arena.desktop.text_action as ta

    monkeypatch.setattr(ta, "resolve_text_window_target", _resolve)
    monkeypatch.setattr(ta, "perform_window_action", _action)

    focus = asyncio.run(run_text_action(action="focus", query="Arena", capture_screenshot=ub.capture_desktop_screenshot, desktop_exec=_exec, detect_env=lambda: {"session_type": "wayland", "has_xdotool": False}, get_active_window=lambda: None, kwin_windows_via_script=lambda: None, ocr_desktop=ub.ocr_desktop, focus_window=_focus, kwin_focus_window=lambda *args, **kwargs: {"ok": True}, audit_fn=None))
    assert focus["ok"] is True
    assert focus["focus_result"]["tool"] == "kwin_focus_script"

    action = asyncio.run(run_text_action(action="center", query="Arena", capture_screenshot=ub.capture_desktop_screenshot, desktop_exec=_exec, detect_env=lambda: {"session_type": "wayland", "has_xdotool": False}, get_active_window=lambda: None, kwin_windows_via_script=lambda: None, ocr_desktop=ub.ocr_desktop, focus_window=_focus, kwin_focus_window=lambda *args, **kwargs: {"ok": True}, audit_fn=None))
    assert action["ok"] is True
    assert action["window_action_result"]["action"] == "center"



def test_text_action_handler_and_registry(monkeypatch):
    import arena.desktop.text_action as ta

    monkeypatch.setattr(ta, "resolve_text_window_target", _resolve)
    monkeypatch.setattr(ta, "perform_window_action", _action)

    handler = make_desktop_text_action_handler(_ctx())
    req = make_mocked_request("POST", "/v1/desktop/text_action", headers={"Authorization": "Bearer t"})

    async def _json():
        return {"action": "center", "query": "Arena", "dry_run": True}

    req.json = _json
    resp = asyncio.run(handler(req))
    data = json.loads(resp.text)
    assert data["ok"] is True
    assert data["workflow_action"] == "center"
    assert data["dry_run"] is True
    assert data["planned_geometry"]["width"] == 900

    names = [tool["name"] for tool in MCP_TOOLS]
    assert "desktop.resolve_text_target" in names
    assert "desktop.text_action" in names
    ctx2 = type("Ctx", (), {"app_config": staticmethod(lambda: {"port": 8765, "token": "t"})})()
    assert handle_desktop_tool("not-desktop", {}, ctx=ctx2) is None

"""Window-relative desktop app MCP tools."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_desktop_app import handle_desktop_app_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402

WINDOWS_PAYLOAD = {
    "ok": True,
    "count": 1,
    "all_count": 1,
    "windows": [
        {
            "id": "w-ce",
            "internal_id": "w-ce",
            "title": "Cheat Engine",
            "pid": 10120,
            "resource_class": "TCustomForm",
            "geometry": {"x": 20, "y": 20, "width": 1000, "height": 700},
        }
    ],
}


def _text(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def test_desktop_app_tools_are_registered():
    names = {tool["name"] for tool in MCP_TOOLS}
    assert "desktop_app.find" in names
    assert "desktop_app.focus" in names
    assert "desktop_app.click_window_relative" in names
    assert "desktop_app.screenshot_window" in names
    assert "desktop_app.type_window" in names
    assert "desktop_app.key_window" in names


def test_desktop_app_find_returns_target_geometry(monkeypatch):
    import arena.mcp.tool_desktop_app as app

    def fake_get(ctx, path, params=None):
        assert path == "/v1/desktop/windows"
        assert params["title"] == "Cheat Engine"
        return WINDOWS_PAYLOAD

    monkeypatch.setattr(app, "_bridge_get", fake_get)
    payload = _text(handle_desktop_app_tool("desktop_app.find", {"title": "Cheat Engine"}, ctx=object()))
    assert payload["ok"] is True
    assert payload["target"]["id"] == "w-ce"
    assert payload["geometry"] == {"x": 20, "y": 20, "width": 1000, "height": 700}


def test_click_window_relative_converts_to_absolute_and_focuses(monkeypatch):
    import arena.mcp.tool_desktop_app as app

    calls = []

    def fake_get(ctx, path, params=None):
        calls.append(("GET", path, params))
        return WINDOWS_PAYLOAD

    def fake_call(ctx, path, payload):
        calls.append(("POST", path, payload))
        return {"ok": True, "path": path}

    monkeypatch.setattr(app, "_bridge_get", fake_get)
    monkeypatch.setattr(app, "_bridge_call", fake_call)
    payload = _text(handle_desktop_app_tool(
        "desktop_app.click_window_relative",
        {"title": "Cheat Engine", "x": 36, "y": 70, "require_active_title": "Cheat"},
        ctx=object(),
    ))
    assert payload["ok"] is True
    assert payload["relative"] == {"x": 36, "y": 70}
    assert payload["absolute"] == {"x": 56, "y": 90}
    assert calls[1] == ("POST", "/v1/desktop/focus", {"id": "w-ce", "verify": True, "timeout_ms": 1500})
    assert calls[2] == ("POST", "/v1/desktop/click", {"x": 56, "y": 90, "button": "left", "double": False, "activate": True, "require_active_title": "Cheat"})


def test_click_window_relative_refuses_outside_by_default(monkeypatch):
    import arena.mcp.tool_desktop_app as app

    monkeypatch.setattr(app, "_bridge_get", lambda ctx, path, params=None: WINDOWS_PAYLOAD)
    payload = _text(handle_desktop_app_tool("desktop_app.click_window_relative", {"title": "Cheat Engine", "x": 5000, "y": 70}, ctx=object()))
    assert payload["ok"] is False
    assert payload["error"] == "relative_point_outside_window"


def test_screenshot_window_uses_window_crop(monkeypatch):
    import arena.mcp.tool_desktop_app as app

    calls = []

    def fake_get(ctx, path, params=None):
        calls.append((path, params))
        if path == "/v1/desktop/windows":
            return WINDOWS_PAYLOAD
        return {"ok": True, "format": "base64", "encoding": "png", "data": "abc"}

    monkeypatch.setattr(app, "_bridge_get", fake_get)
    payload = _text(handle_desktop_app_tool("desktop_app.screenshot_window", {"title": "Cheat Engine", "max_width": 500}, ctx=object()))
    assert payload["ok"] is True
    assert payload["target"]["title"] == "Cheat Engine"
    assert calls[1] == (
        "/v1/desktop/screenshot",
        {"format": "base64", "region_x": 20, "region_y": 20, "region_width": 1000, "region_height": 700, "quality": 80, "max_width": 500},
    )


def test_desktop_screenshot_accepts_explicit_region_crop(monkeypatch):
    import asyncio
    import json

    from aiohttp.test_utils import make_mocked_request

    import unified_bridge as ub
    from arena.desktop.screenshot_handler import make_desktop_screenshot_handler
    from arena.handler_context import DesktopHandlerContext

    seen = {}

    async def fake_capture(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "bytes": b"png", "encoding": "png", "tool": "fake", "transformed": False, "crop_region": {"x": kwargs["region_x"], "y": kwargs["region_y"], "width": kwargs["region_width"], "height": kwargs["region_height"]}}

    ctx = DesktopHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        control_check=ub._control_check,
        control_record_agent_action=ub._control_record_agent_action,
        desktop_exec=ub._desktop_exec,
        detect_desktop_env=lambda: {},
        get_active_window=ub._get_active_window,
        kwin_windows_via_script=ub._kwin_windows_via_script,
        capture_screenshot=fake_capture,
        ocr_desktop=ub.ocr_desktop,
        kwin_focus_window=ub.kwin_focus_window_via_script,
        focus_window=ub.focus_window,
        audit=ub.audit,
    )
    handler = make_desktop_screenshot_handler(ctx)
    req = make_mocked_request("GET", "/v1/desktop/screenshot?format=base64&region_x=20&region_y=30&region_width=400&region_height=300")
    resp = asyncio.run(handler(req))
    assert resp.status == 200
    payload = json.loads(resp.text)
    assert payload["ok"] is True
    assert payload["crop_region"] == {"x": 20, "y": 30, "width": 400, "height": 300}
    assert seen["region_x"] == 20
    assert seen["region_y"] == 30
    assert seen["region_width"] == 400
    assert seen["region_height"] == 300

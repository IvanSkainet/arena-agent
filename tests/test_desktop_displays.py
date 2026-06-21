"""Desktop display/output discovery regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.desktop.display_handler import make_desktop_display_handler  # noqa: E402
from arena.desktop.displays import get_displays, match_display, parse_kscreen_doctor_outputs, parse_xrandr_outputs  # noqa: E402
from arena.handler_context import DesktopHandlerContext  # noqa: E402
from arena.mcp.tool_desktop import handle_desktop_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
import unified_bridge as ub  # noqa: E402


KSCREEN_SAMPLE = """
\x1b[01;32mOutput: \x1b[0;0m1 DP-1 uuid-1
\t\x1b[01;32menabled\x1b[0;0m
\t\x1b[01;32mconnected\x1b[0;0m
\t\x1b[01;33m\tGeometry: \x1b[0;0m0,0 2560x1440
\x1b[01;32mOutput: \x1b[0;0m2 HDMI-A-1 uuid-2
\t\x1b[01;32menabled\x1b[0;0m
\t\x1b[01;32mconnected\x1b[0;0m
\t\x1b[01;33m\tGeometry: \x1b[0;0m2560,0 1920x1080
"""

XRANDR_SAMPLE = """
DP-1 connected primary 2560x1440+0+0 (normal left inverted right x axis y axis)
HDMI-1 connected 1920x1080+2560+0 (normal left inverted right x axis y axis)
"""


async def _display_exec(cmd: str, timeout: float = 10):
    if "activeOutputName" in cmd:
        return {"ok": True, "stdout": "DP-1\n", "stderr": ""}
    if "kscreen-doctor -o" in cmd:
        return {"ok": True, "stdout": KSCREEN_SAMPLE, "stderr": ""}
    return {"ok": False, "stdout": "", "stderr": "unexpected"}



def _ctx(exec_fn=_display_exec):
    return DesktopHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        control_check=lambda: None,
        control_record_agent_action=lambda: None,
        desktop_exec=exec_fn,
        detect_desktop_env=lambda: {},
        get_active_window=lambda: None,
        kwin_windows_via_script=lambda: None,
        capture_screenshot=ub.capture_desktop_screenshot,
        ocr_desktop=ub.ocr_desktop,
        kwin_focus_window=lambda *args, **kwargs: {"ok": False},
        focus_window=lambda **kwargs: {},
        audit=lambda event: None,
    )



def test_parse_display_outputs_and_match_display():
    kscreen = parse_kscreen_doctor_outputs(KSCREEN_SAMPLE)
    assert len(kscreen) == 2
    assert kscreen[0]["name"] == "DP-1"
    assert kscreen[1]["geometry"]["x"] == 2560

    xrandr = parse_xrandr_outputs(XRANDR_SAMPLE)
    assert len(xrandr) == 2
    assert xrandr[0]["primary"] is True
    assert xrandr[1]["geometry"]["width"] == 1920

    assert match_display(kscreen, "DP-1")["uuid"] == "uuid-1"
    assert match_display(kscreen, "uuid-2")["name"] == "HDMI-A-1"
    assert match_display(kscreen, "missing") is None



def test_get_displays_prefers_kscreen_doctor():
    result = asyncio.run(get_displays(desktop_exec=_display_exec))
    assert result["ok"] is True
    assert result["backend"] == "kscreen_doctor"
    assert result["active_output"] == "DP-1"
    assert result["count"] == 2
    assert result["displays"][0]["active"] is True



def test_desktop_display_handler_and_routes():
    handler = make_desktop_display_handler(_ctx())
    req = make_mocked_request("GET", "/v1/desktop/displays", headers={"Authorization": "Bearer t"})
    resp = asyncio.run(handler(req))
    data = json.loads(resp.text)
    assert data["ok"] is True
    assert data["count"] == 2
    assert data["displays"][1]["name"] == "HDMI-A-1"

    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/desktop/displays") in paths



def test_desktop_displays_mcp_registry():
    ctx = type("Ctx", (), {"app_config": staticmethod(lambda: {"port": 8765, "token": "t"})})()
    names = [tool["name"] for tool in MCP_TOOLS]
    assert "desktop.displays" in names
    assert handle_desktop_tool("not-desktop", {}, ctx=ctx) is None

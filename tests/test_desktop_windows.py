"""Desktop window catalog, filters, and focus regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.desktop.focus import focus_window  # noqa: E402
from arena.desktop.window_catalog import annotate_windows_with_displays, list_desktop_windows, window_candidates  # noqa: E402
from arena.desktop.window_handlers import make_desktop_window_handlers  # noqa: E402
from arena.handler_context import DesktopHandlerContext  # noqa: E402
import unified_bridge as ub  # noqa: E402


async def _kwin_list():
    return {
        "ok": True,
        "backend": "kwin_journal",
        "count": 2,
        "windows": [
            {"id": "{browser}", "internal_id": "{browser}", "title": "Arena – LibreWolf", "pid": 111, "resource_class": "librewolf", "resource_name": "librewolf", "desktop_file": "librewolf", "active": True, "geometry": {"x": 0, "y": 0, "width": 1200, "height": 900}},
            {"id": "{editor}", "internal_id": "{editor}", "title": "Code - repo", "pid": 222, "resource_class": "code", "resource_name": "code", "desktop_file": "code", "active": False, "geometry": {"x": 2560, "y": 0, "width": 1400, "height": 1000}},
        ],
    }


async def _exec(cmd: str, timeout: float = 10):
    if "activeOutputName" in cmd:
        return {"ok": True, "stdout": "DP-1\n", "stderr": ""}
    if "kscreen-doctor -o" in cmd:
        return {"ok": True, "stdout": "Output: 1 DP-1 uuid-1\n\tenabled\n\tconnected\n\tGeometry: 0,0 2560x1440\nOutput: 2 HDMI-A-1 uuid-2\n\tenabled\n\tconnected\n\tGeometry: 2560,0 1920x1080\n", "stderr": ""}
    return {"ok": True, "stdout": "", "stderr": "", "exit_code": 0}


async def _active_browser():
    return {"id": "{browser}", "title": "Arena – LibreWolf", "backend": "kwin_journal"}



def test_annotate_and_filter_window_candidates():
    windows = [
        {"id": "1", "title": "Arena – LibreWolf", "resource_class": "librewolf", "desktop_file": "librewolf", "pid": 111, "active": True, "geometry": {"x": 0, "y": 0, "width": 1000, "height": 800}},
        {"id": "2", "title": "Code - repo", "resource_class": "code", "desktop_file": "code", "pid": 222, "active": False, "geometry": {"x": 2600, "y": 0, "width": 1200, "height": 900}},
    ]
    displays = [
        {"name": "DP-1", "id": "DP-1", "geometry": {"x": 0, "y": 0, "width": 2560, "height": 1440}, "active": True},
        {"name": "HDMI-A-1", "id": "HDMI-A-1", "geometry": {"x": 2560, "y": 0, "width": 1920, "height": 1080}, "active": False},
    ]
    annotated = annotate_windows_with_displays(windows, displays)
    assert annotated[0]["display"]["name"] == "DP-1"
    assert annotated[1]["display"]["name"] == "HDMI-A-1"

    by_title = window_candidates(annotated, title="Arena")
    assert by_title[0]["id"] == "1"
    by_display = window_candidates(annotated, display="HDMI-A-1")
    assert len(by_display) == 1 and by_display[0]["id"] == "2"
    by_class = window_candidates(annotated, class_contains="code")
    assert by_class[0]["desktop_file"] == "code"



def test_list_desktop_windows_annotates_displays():
    result = asyncio.run(list_desktop_windows(desktop_exec=_exec, detect_env=lambda: {"has_xdotool": False}, kwin_windows_via_script=_kwin_list))
    assert result["ok"] is True
    assert result["windows"][0]["display"]["name"] == "DP-1"
    assert result["windows"][1]["display"]["name"] == "HDMI-A-1"



def test_focus_window_uses_kwin_script_for_uuid_targets():
    calls = []

    async def _kwin_focus(target_id: str, *, desktop_exec):
        calls.append(target_id)
        return {"ok": True, "backend": "kwin_focus_script"}

    result = asyncio.run(
        focus_window(
            window_id="{browser}",
            target_title="Arena – LibreWolf",
            desktop_exec=_exec,
            detect_env=lambda: {"session_type": "wayland", "has_xdotool": False},
            get_active_window=_active_browser,
            kwin_focus_window=_kwin_focus,
        )
    )
    assert result["ok"] is True
    assert result["tool"] == "kwin_focus_script"
    assert calls == ["{browser}"]



def test_window_handlers_support_filters_and_focus_dry_run():
    async def _active_window():
        return {"id": "{browser}", "title": "Arena – LibreWolf", "backend": "kwin_journal"}

    ctx = DesktopHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        control_check=lambda: None,
        control_record_agent_action=lambda: None,
        desktop_exec=_exec,
        detect_desktop_env=lambda: {"has_xdotool": False},
        get_active_window=_active_window,
        kwin_windows_via_script=_kwin_list,
        capture_screenshot=ub.capture_desktop_screenshot,
        ocr_desktop=ub.ocr_desktop,
        kwin_focus_window=lambda *args, **kwargs: {"ok": True, "backend": "kwin_focus_script"},
        focus_window=focus_window,
        audit=lambda event: None,
    )
    windows_handler, _, focus_handler = make_desktop_window_handlers(ctx)

    req = make_mocked_request("GET", "/v1/desktop/windows?display=HDMI-A-1&include_displays=1", headers={"Authorization": "Bearer t"})
    resp = asyncio.run(windows_handler(req))
    data = json.loads(resp.text)
    assert data["count"] == 1
    assert data["windows"][0]["title"] == "Code - repo"
    assert len(data["displays"]) == 2

    focus_req = make_mocked_request("POST", "/v1/desktop/focus", headers={"Authorization": "Bearer t"})

    async def _json():
        return {"class": "code", "display": "HDMI-A-1", "dry_run": True}

    focus_req.json = _json
    focus_resp = asyncio.run(focus_handler(focus_req))
    focus_data = json.loads(focus_resp.text)
    assert focus_data["ok"] is True
    assert focus_data["dry_run"] is True
    assert focus_data["target_title"] == "Code - repo"

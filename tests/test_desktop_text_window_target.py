"""Desktop OCR-to-window target resolution regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.desktop.text_window_handler import make_desktop_text_window_handler  # noqa: E402
from arena.desktop.text_window_target import resolve_text_window_target  # noqa: E402
from arena.handler_context import DesktopHandlerContext  # noqa: E402
import unified_bridge as ub  # noqa: E402


async def _ocr_echo(**kwargs):
    return {
        "ok": True,
        "query": kwargs.get("query", ""),
        "matches": [{"text": "Arena", "bbox": {"x": 130, "y": 140, "width": 60, "height": 20}, "center": {"x": 160, "y": 150}, "score": 1.0, "match_type": "exact"}],
        "best_match": {"text": "Arena", "bbox": {"x": 130, "y": 140, "width": 60, "height": 20}, "center": {"x": 160, "y": 150}, "score": 1.0, "match_type": "exact"},
        "text": "Arena",
        "words": [],
        "word_count": 0,
    }


async def _exec(cmd: str, timeout: float = 10):
    if "activeOutputName" in cmd:
        return {"ok": True, "stdout": "DP-1\n", "stderr": ""}
    if "kscreen-doctor -o" in cmd:
        return {"ok": True, "stdout": "Output: 1 DP-1 uuid-1\n\tenabled\n\tconnected\n\tGeometry: 0,0 2560x1440\n", "stderr": ""}
    return {"ok": True, "stdout": "", "stderr": "", "exit_code": 0}


async def _active_window():
    return {"id": "{browser}", "title": "Arena Page", "geometry": {"x": 0, "y": 0, "width": 1200, "height": 900}}


async def _kwin_list():
    return {
        "ok": True,
        "backend": "kwin_journal",
        "count": 2,
        "windows": [
            {"id": "{browser}", "internal_id": "{browser}", "title": "Arena Page", "pid": 111, "resource_class": "librewolf", "resource_name": "librewolf", "desktop_file": "librewolf", "active": True, "geometry": {"x": 0, "y": 0, "width": 1200, "height": 900}},
            {"id": "{editor}", "internal_id": "{editor}", "title": "Code - repo", "pid": 222, "resource_class": "code", "resource_name": "code", "desktop_file": "code", "active": False, "geometry": {"x": 1400, "y": 100, "width": 900, "height": 700}},
        ],
    }



def _ctx():
    return DesktopHandlerContext(
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
        ocr_desktop=_ocr_echo,
        kwin_focus_window=lambda *args, **kwargs: {"ok": True},
        focus_window=ub.focus_window,
        audit=lambda event: None,
    )



def test_resolve_text_window_target_basic_shape():
    result = asyncio.run(resolve_text_window_target(query="Arena", capture_screenshot=ub.capture_desktop_screenshot, desktop_exec=_exec, detect_env=lambda: {"session_type": "wayland", "has_xdotool": False}, get_active_window=_active_window, kwin_windows_via_script=_kwin_list, ocr_desktop=_ocr_echo, audit_fn=None))
    assert result["ok"] is True
    assert result["target_window"]["id"] == "{browser}"
    assert result["best_match"]["text"] == "Arena"
    assert result["window_candidates"][0]["title"] == "Arena Page"



def test_resolve_text_window_target_respects_window_filters():
    result = asyncio.run(resolve_text_window_target(query="Arena", window_title="Arena Page", class_contains="librewolf", capture_screenshot=ub.capture_desktop_screenshot, desktop_exec=_exec, detect_env=lambda: {"session_type": "wayland", "has_xdotool": False}, get_active_window=_active_window, kwin_windows_via_script=_kwin_list, ocr_desktop=_ocr_echo, audit_fn=None))
    assert result["ok"] is True
    assert result["target_window"]["resource_class"] == "librewolf"



def test_resolve_text_window_target_can_crop_to_active_window():
    captured = {}

    async def _ocr_capture(**kwargs):
        captured.update(kwargs)
        return await _ocr_echo(**kwargs)

    result = asyncio.run(resolve_text_window_target(query="Arena", crop_active_window=True, capture_screenshot=ub.capture_desktop_screenshot, desktop_exec=_exec, detect_env=lambda: {"session_type": "wayland", "has_xdotool": False}, get_active_window=_active_window, kwin_windows_via_script=_kwin_list, ocr_desktop=_ocr_capture, audit_fn=None))
    assert result["ok"] is True
    assert result["crop_active_window"] is True
    assert captured["region_x"] == 0
    assert captured["region_width"] == 1200



def test_resolve_text_window_handler_route_and_body():
    handler = make_desktop_text_window_handler(_ctx())
    req = make_mocked_request("POST", "/v1/desktop/resolve_text_target", headers={"Authorization": "Bearer t"})

    async def _json():
        return {"query": "Arena", "class": "librewolf"}

    req.json = _json
    resp = asyncio.run(handler(req))
    data = json.loads(resp.text)
    assert data["ok"] is True
    assert data["target_window"]["id"] == "{browser}"

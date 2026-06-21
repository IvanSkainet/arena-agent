"""Desktop OCR, text ranking, and semantic click regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.desktop.ocr import build_ocr_text, find_text_matches, ocr_desktop, parse_tesseract_tsv  # noqa: E402
from arena.desktop.ocr_handler import make_desktop_ocr_handlers  # noqa: E402
from arena.handler_context import DesktopHandlerContext  # noqa: E402
from arena.mcp.tool_desktop import handle_desktop_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
import unified_bridge as ub  # noqa: E402


SAMPLE_TSV = """level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext
5\t1\t1\t1\t1\t1\t10\t20\t50\t20\t90\tHello
5\t1\t1\t1\t1\t2\t70\t20\t40\t20\t88\tWorld
5\t1\t1\t1\t2\t1\t10\t60\t60\t20\t85\tArena
"""


async def _fake_capture(**kwargs):
    return {"ok": True, "bytes": b"fakepng", "encoding": "png", "tool": "spectacle", "transformed": False}


async def _fake_exec(cmd: str, timeout: float = 10):
    if "tesseract" in cmd:
        return {"ok": True, "stdout": SAMPLE_TSV, "stderr": ""}
    return {"ok": True, "stdout": "", "stderr": ""}



def _word(text: str, x: int, y: int, *, line: int = 1, conf: float = 90.0):
    return {
        "text": text,
        "confidence": conf,
        "bbox": {"x": x, "y": y, "width": max(18, len(text) * 8), "height": 18},
        "center": {"x": x + max(18, len(text) * 8) // 2, "y": y + 9},
        "line_num": line,
        "block_num": 1,
        "par_num": 1,
    }



def test_parse_tesseract_tsv_and_find_matches():
    words = parse_tesseract_tsv(SAMPLE_TSV, min_confidence=40)
    assert len(words) == 3
    assert words[0]["text"] == "Hello"
    assert build_ocr_text(words) == "Hello World\nArena"
    matches = find_text_matches(words, "Hello World")
    assert matches
    assert matches[0]["text"] == "Hello World"
    assert matches[0]["center"]["x"] > 0
    assert matches[0]["match_type"] == "exact"



def test_find_text_matches_ranks_exact_above_tiny_substring_noise():
    words = [_word("o", 10, 10), _word("Google", 120, 10, line=2)]
    matches = find_text_matches(words, "Google")
    assert matches
    assert matches[0]["text"] == "Google"
    assert all(match["text"] != "o" for match in matches)



def test_find_text_matches_can_prefer_or_filter_active_window_geometry():
    words = [_word("Settings", 10, 10), _word("Settings", 320, 10)]
    active_window = {"x": 250, "y": 0, "width": 300, "height": 120}

    preferred = find_text_matches(words, "Settings", prefer_active_window=True, active_window_geometry=active_window)
    assert preferred[0]["inside_active_window"] is True
    assert preferred[0]["bbox"]["x"] >= 300

    scoped = find_text_matches(words, "Settings", within_active_window=True, active_window_geometry=active_window)
    assert len(scoped) == 1
    assert scoped[0]["inside_active_window"] is True
    assert scoped[0]["bbox"]["x"] >= 300



def test_ocr_desktop_shape():
    import arena.desktop.ocr as ocr

    original = ocr.shutil.which
    ocr.shutil.which = lambda name: "/usr/bin/tesseract" if name == "tesseract" else None
    try:
        result = asyncio.run(
            ocr_desktop(
                query="Arena",
                prefer_active_window=True,
                active_window={"title": "Arena", "geometry": {"x": 0, "y": 40, "width": 400, "height": 80}},
                capture_screenshot=_fake_capture,
                desktop_exec=_fake_exec,
                detect_env=lambda: {},
                audit_fn=None,
            )
        )
        assert result["ok"] is True
        assert result["best_match"]["text"] == "Arena"
        assert result["prefer_active_window"] is True
        assert result["active_window"]["title"] == "Arena"
    finally:
        ocr.shutil.which = original



def _desktop_ctx():
    async def _active_window():
        return {"id": "win-1", "title": "Arena", "geometry": {"x": 0, "y": 40, "width": 400, "height": 80}}

    return DesktopHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        control_check=lambda: None,
        control_record_agent_action=lambda: None,
        desktop_exec=_fake_exec,
        detect_desktop_env=lambda: {"has_xdotool": True},
        get_active_window=_active_window,
        kwin_windows_via_script=lambda: None,
        capture_screenshot=_fake_capture,
        ocr_desktop=ocr_desktop,
        kwin_focus_window=lambda *args, **kwargs: {"ok": False},
        focus_window=lambda **kwargs: {},
        audit=lambda event: None,
    )



def test_desktop_ocr_handlers_routes_and_click_text(monkeypatch):
    import arena.desktop.ocr as ocr

    original = ocr.shutil.which
    ocr.shutil.which = lambda name: "/usr/bin/tesseract" if name == "tesseract" else None
    try:
        handlers = make_desktop_ocr_handlers(_desktop_ctx())

        req = make_mocked_request("POST", "/v1/desktop/find_text", headers={"Authorization": "Bearer t"})

        async def _json_find():
            return {"query": "Arena", "prefer_active_window": True}

        req.json = _json_find
        resp = asyncio.run(handlers.find_text(req))
        data = json.loads(resp.text)
        assert data["ok"] is True
        assert data["best_match"]["text"] == "Arena"
        assert data["best_match"]["inside_active_window"] is True

        click_req = make_mocked_request("POST", "/v1/desktop/click_text", headers={"Authorization": "Bearer t"})

        async def _json_click():
            return {
                "query": "Arena",
                "prefer_active_window": True,
                "target_position": "right",
                "offset_x": 5,
                "dry_run": True,
            }

        click_req.json = _json_click
        click_resp = asyncio.run(handlers.click_text(click_req))
        click_data = json.loads(click_resp.text)
        assert click_data["ok"] is True
        assert click_data["clicked"] is False
        assert click_data["target"]["position"] == "right"
        assert click_data["target"]["x"] > click_data["best_match"]["center"]["x"]

        live_click_req = make_mocked_request("POST", "/v1/desktop/click_text", headers={"Authorization": "Bearer t"})

        async def _json_live_click():
            return {"query": "Arena", "prefer_active_window": True}

        live_click_req.json = _json_live_click
        live_click_resp = asyncio.run(handlers.click_text(live_click_req))
        live_click_data = json.loads(live_click_resp.text)
        assert live_click_data["ok"] is True
        assert live_click_data["clicked"] is True
        assert live_click_data["click_tool"] == "xdotool"

        app = ub.make_app({"token": "test"})
        paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
        assert ("POST", "/v1/desktop/ocr") in paths
        assert ("POST", "/v1/desktop/find_text") in paths
        assert ("POST", "/v1/desktop/click_text") in paths
    finally:
        ocr.shutil.which = original



def test_ocr_handler_resolves_display_crop(monkeypatch):
    import arena.desktop.ocr_handler as oh

    captured = {}

    async def _ocr_echo(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "query": kwargs.get("query", ""), "matches": [{"text": "Arena", "bbox": {"x": 2600, "y": 20, "width": 40, "height": 18}, "center": {"x": 2620, "y": 29}}], "best_match": {"text": "Arena", "bbox": {"x": 2600, "y": 20, "width": 40, "height": 18}, "center": {"x": 2620, "y": 29}}, "text": "Arena", "words": [], "word_count": 0}

    async def _active_window():
        return {"id": "win-1", "title": "Arena", "geometry": {"x": 2500, "y": 0, "width": 500, "height": 500}}

    monkeypatch.setattr(
        oh,
        "get_displays",
        lambda **kwargs: asyncio.sleep(0, result={"ok": True, "displays": [{"name": "HDMI-A-1", "geometry": {"x": 2560, "y": 0, "width": 1920, "height": 1080}}]}),
    )
    ctx = DesktopHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        control_check=lambda: None,
        control_record_agent_action=lambda: None,
        desktop_exec=_fake_exec,
        detect_desktop_env=lambda: {"has_xdotool": True},
        get_active_window=_active_window,
        kwin_windows_via_script=lambda: None,
        capture_screenshot=_fake_capture,
        ocr_desktop=_ocr_echo,
        kwin_focus_window=lambda *args, **kwargs: {"ok": False},
        focus_window=lambda **kwargs: {},
        audit=lambda event: None,
    )
    handlers = make_desktop_ocr_handlers(ctx)
    req = make_mocked_request("POST", "/v1/desktop/find_text", headers={"Authorization": "Bearer t"})

    async def _json():
        return {"query": "Arena", "display": "HDMI-A-1"}

    req.json = _json
    resp = asyncio.run(handlers.find_text(req))
    data = json.loads(resp.text)
    assert data["ok"] is True
    assert data["display"]["name"] == "HDMI-A-1"
    assert captured["region_x"] == 2560
    assert captured["region_width"] == 1920



def test_desktop_mcp_tools_registry():
    ctx = type("Ctx", (), {"app_config": staticmethod(lambda: {"port": 8765, "token": "t"})})()
    names = [tool["name"] for tool in MCP_TOOLS]
    assert "desktop.displays" in names
    assert "desktop.windows" in names
    assert "desktop.focus" in names
    assert "desktop.ocr" in names
    assert "desktop.find_text" in names
    assert "desktop.click_text" in names
    assert handle_desktop_tool("not-desktop", {}, ctx=ctx) is None

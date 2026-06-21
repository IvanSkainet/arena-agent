"""Desktop OCR parsing, handlers, and MCP regressions."""
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


def test_parse_tesseract_tsv_and_find_matches():
    words = parse_tesseract_tsv(SAMPLE_TSV, min_confidence=40)
    assert len(words) == 3
    assert words[0]["text"] == "Hello"
    assert build_ocr_text(words) == "Hello World\nArena"
    matches = find_text_matches(words, "Hello World")
    assert matches
    assert matches[0]["text"] == "Hello World"
    assert matches[0]["center"]["x"] > 0


async def _fake_capture(**kwargs):
    return {"ok": True, "bytes": b'fakepng', "encoding": 'png', "tool": 'spectacle', "transformed": False}


async def _fake_exec(cmd: str, timeout: float = 10):
    return {"ok": True, "stdout": SAMPLE_TSV, "stderr": ""}


def test_ocr_desktop_shape():
    import arena.desktop.ocr as ocr
    original = ocr.shutil.which
    ocr.shutil.which = lambda name: "/usr/bin/tesseract" if name == "tesseract" else None
    try:
        result = asyncio.run(ocr_desktop(query="Arena", capture_screenshot=_fake_capture, desktop_exec=_fake_exec, detect_env=lambda: {}, audit_fn=None))
        assert result["ok"] is True
        assert result["best_match"]["text"] == "Arena"
    finally:
        ocr.shutil.which = original



def _desktop_ctx():
    return DesktopHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        control_check=lambda: None,
        control_record_agent_action=lambda: None,
        desktop_exec=_fake_exec,
        detect_desktop_env=lambda: {},
        get_active_window=lambda: None,
        kwin_windows_via_script=lambda: None,
        capture_screenshot=_fake_capture,
        ocr_desktop=ocr_desktop,
        focus_window=lambda **kwargs: {},
        audit=lambda event: None,
    )


def test_desktop_ocr_handlers_and_routes(monkeypatch):
    import arena.desktop.ocr as ocr
    original = ocr.shutil.which
    ocr.shutil.which = lambda name: "/usr/bin/tesseract" if name == "tesseract" else None
    try:
        handlers = make_desktop_ocr_handlers(_desktop_ctx())
        req = make_mocked_request("POST", "/v1/desktop/find_text", headers={"Authorization": "Bearer t"})
        async def _json():
            return {"query": "Arena"}
        req.json = _json
        resp = asyncio.run(handlers.find_text(req))
        data = json.loads(resp.text)
        assert data["ok"] is True
        assert data["best_match"]["text"] == "Arena"

        app = ub.make_app({"token": "test"})
        paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
        assert ("POST", "/v1/desktop/ocr") in paths
        assert ("POST", "/v1/desktop/find_text") in paths
    finally:
        ocr.shutil.which = original


def test_desktop_mcp_tools_registry():
    ctx = type("Ctx", (), {"app_config": staticmethod(lambda: {"port": 8765, "token": "t"})})()
    names = [tool["name"] for tool in MCP_TOOLS]
    assert "desktop.ocr" in names
    assert "desktop.find_text" in names
    # dispatch function smoke: wrong/missing network isn't exercised here, only unknown handling
    assert handle_desktop_tool("not-desktop", {}, ctx=ctx) is None

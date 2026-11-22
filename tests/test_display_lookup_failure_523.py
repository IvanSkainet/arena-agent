"""#523: a display list that could not be read is a server error, not an unknown display name."""
from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp.test_utils import make_mocked_request

import unified_bridge as ub
from arena.desktop import display_lookup
from arena.desktop.backends import windows_displays
from arena.desktop.ocr_handler import make_desktop_ocr_handlers
from arena.desktop.screenshot_handler import make_desktop_screenshot_handler
from arena.desktop.text_window_target import resolve_text_window_target
from arena.handler_context import DesktopHandlerContext

DISPLAY = {"name": "DISPLAY1", "id": "1", "active": True, "geometry": {"x": 0, "y": 0, "width": 2560, "height": 1440}}
LISTED = {"ok": True, "displays": [DISPLAY]}
UNREADABLE = "EnumDisplayMonitors failed: no interactive desktop"


async def _nothing(*args, **kwargs):
    return None


def _context():
    return DesktopHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        control_check=lambda: None,
        control_record_agent_action=lambda: None,
        desktop_exec=_nothing,
        detect_desktop_env=lambda: {"has_win32_windows": True},
        get_active_window=_nothing,
        kwin_windows_via_script=_nothing,
        capture_screenshot=_nothing,
        ocr_desktop=_nothing,
        kwin_focus_window=_nothing,
        focus_window=_nothing,
        audit=lambda event: None,
    )


def _screenshot(display):
    request = make_mocked_request("GET", f"/v1/desktop/screenshot?display={display}", headers={"Authorization": "Bearer t"})
    return asyncio.run(make_desktop_screenshot_handler(_context())(request))


def _find_text(display):
    request = make_mocked_request("POST", "/v1/desktop/find_text", headers={"Authorization": "Bearer t"})

    async def body():
        return {"query": "Arena", "display": display}

    request.json = body
    return asyncio.run(make_desktop_ocr_handlers(_context()).find_text(request))


def _text_window_target(display):
    answer = asyncio.run(resolve_text_window_target(
        query="Arena", display=display, prefer_active_window=False, capture_screenshot=_nothing, desktop_exec=_nothing,
        detect_env=lambda: {"has_win32_windows": True}, get_active_window=_nothing, kwin_windows_via_script=_nothing, ocr_desktop=_nothing,
    ))
    return answer["status"], answer


def _over_http(call):
    def answer(display):
        response = call(display)
        return response.status, json.loads(response.text)
    return answer


CALLERS = pytest.mark.parametrize(
    "ask", [_over_http(_screenshot), _over_http(_find_text), _text_window_target], ids=["screenshot", "find_text", "text_window_target"],
)


@pytest.fixture(name="unreadable")
def _unreadable(monkeypatch):
    """Windows refuses to enumerate its monitors, as it does for a process without a desktop."""
    def refuse():
        raise OSError(UNREADABLE)

    monkeypatch.setattr(windows_displays, "list_displays", refuse)


@pytest.fixture(name="one_display")
def _one_display(monkeypatch):
    """Windows lists a single monitor."""
    monkeypatch.setattr(windows_displays, "list_displays", lambda: [dict(DISPLAY)])


@CALLERS
def test_an_unreadable_display_list_is_a_server_error(ask, unreadable):
    """The caller's display name may well be right; nobody could check."""
    status, body = ask("DISPLAY1")
    assert status == 500
    assert UNREADABLE in body["error"]
    assert "unknown display" not in body["error"]
    assert "available_displays" not in body


@CALLERS
def test_a_name_missing_from_a_readable_list_is_still_not_found(ask, one_display):
    """Unchanged: 404, and the displays that do exist."""
    status, body = ask("DISPLAY7")
    assert status == 404
    assert body["error"] == "unknown display: DISPLAY7"
    assert [display["name"] for display in body["available_displays"]] == ["DISPLAY1"]


def test_a_listed_display_is_chosen_without_a_refusal():
    """Names match the way they always have, whatever their case."""
    assert display_lookup.choose_display(LISTED, "display1") == (DISPLAY, None)


def test_a_listing_that_does_not_say_whether_it_worked_is_trusted():
    """The Linux tools and older stand-ins answer without `ok`; an empty list from them means no such display."""
    display, refusal = display_lookup.choose_display({"displays": []}, "DP-1")
    assert (display, refusal["status"]) == ({}, 404)


def test_the_refusal_names_what_was_tried():
    """So the reader can tell which tool failed."""
    attempts = [{"tool": "user32.EnumDisplayMonitors", "ok": False, "error": UNREADABLE}]
    _, refusal = display_lookup.choose_display({"ok": False, "error": UNREADABLE, "displays": [], "attempts": attempts}, "DISPLAY1")
    assert refusal == {"status": 500, "body": {"ok": False, "error": f"displays could not be listed: {UNREADABLE}", "attempts": attempts}}

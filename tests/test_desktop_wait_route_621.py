"""#621: POST /v1/desktop/wait and MCP `desktop.wait` -- the route, its refusals, the tool, the document."""
# The producers are recorders; the one test that starts a bridge only lists windows.
from __future__ import annotations

import asyncio
import json
import secrets
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from arena.desktop import wait_handler
from arena.mcp import tool_desktop_wait
from arena.mcp.tool_desktop_app import handle_desktop_app_tool
from arena.mcp.tool_registry import MCP_TOOLS
from arena.observability.audit_enhanced import classify_action
from arena.public.openapi import build_openapi_spec
from arena.route_registry.registry import ROUTES
from tests._live_bridge import auth_header, json_payload, running_client

GAME = {"id": "7", "title": "Abyssal Ascent - Minecraft", "class": "GLFW30", "geometry": {"width": 800, "height": 600}}
PICTURE = b"BM first"


class Desk:
    """A handler context whose producers remember how they were asked and answer what the test set."""

    def __init__(self) -> None:
        """A desktop with one window, a screen that never changes and a reader that finds nothing."""
        self.recorded: list[dict] = []
        self.audited: list[dict] = []
        self.asked: list[tuple[str, dict]] = []
        self.listing: dict = {"ok": True, "tool": "wmctrl", "windows": [GAME]}
        self.shot: dict = {"ok": True, "bytes": PICTURE, "encoding": "png"}
        self.read: dict = {"ok": True, "matches": [], "word_count": 3}
        self.front: dict | None = GAME
        self.refuse_auth: web.Response | None = None
        self.desktop_exec = object()
        self.detect_desktop_env = dict
        self.kwin_windows_via_script = object()

    def require_auth(self, _request):
        return self.refuse_auth

    def record_request(self, **kwargs) -> None:
        self.recorded.append(kwargs)

    def audit(self, record: dict) -> None:
        self.audited.append(record)

    @staticmethod
    def cors_json_response(payload, status=200):
        return web.json_response(payload, status=status)

    async def get_active_window(self):
        return self.front

    async def list_windows(self, **kwargs):
        self.asked.append(("windows", kwargs))
        return self.listing

    async def capture_screenshot(self, **kwargs):
        self.asked.append(("capture", kwargs))
        return self.shot

    async def ocr_desktop(self, **kwargs):
        self.asked.append(("ocr", kwargs))
        return self.read


@pytest.fixture(name="desk")
def _desk(monkeypatch) -> Desk:
    desk = Desk()
    monkeypatch.setattr(wait_handler, "list_desktop_windows", desk.list_windows)
    return desk


def post_raw(desk: Desk, body, **send):
    async def go():
        app = web.Application()
        app.router.add_post("/v1/desktop/wait", wait_handler.make_desktop_wait_handler(desk))
        async with TestClient(TestServer(app)) as client:
            response = await client.post("/v1/desktop/wait", **(send or {"json": body}))
            return response.status, await response.text()

    return asyncio.run(go())


def post(desk: Desk, body):
    status, text = post_raw(desk, body)
    return status, json.loads(text)


def test_a_window_that_is_there_is_answered_at_once_and_noted_once(desk):
    status, body = post(desk, {"for": "window", "title": "minecraft"})
    assert status == 200
    assert body == {"ok": True, "happened": True, "for": "window", "waited_ms": body["waited_ms"], "polls": 1,
                    "matches": 1, "window": GAME}
    assert body["waited_ms"] < 500
    assert desk.asked == [("windows", {"desktop_exec": desk.desktop_exec, "detect_env": desk.detect_desktop_env,
                                       "kwin_windows_via_script": desk.kwin_windows_via_script})]
    assert desk.audited == [{"type": "desktop_wait", "for": "window", "happened": True,
                             "waited_ms": body["waited_ms"], "polls": 1}]
    assert desk.recorded == [{}]


def test_time_running_out_is_a_200_that_says_it_did_not_happen(desk):
    status, body = post(desk, {"for": "window", "title": "launcher", "timeout_ms": 250, "poll_ms": 100})
    assert status == 200
    assert (body["ok"], body["happened"], body["matches"]) == (True, False, 0)
    assert body["polls"] >= 3
    assert 250 <= body["waited_ms"] < 2000
    assert desk.audited[0]["happened"] is False
    assert desk.recorded == [{}]


def test_the_active_window_is_asked_from_this_bridge(desk):
    desk.front = {"id": "8", "title": "Notes"}
    status, body = post(desk, {"for": "window", "title": "minecraft", "state": "active", "timeout_ms": 1})
    assert (status, body["happened"], body["active_window"]) == (200, False, {"id": "8", "title": "Notes"})
    assert desk.asked == []


def test_a_screen_wait_captures_the_region_as_png_without_an_audit_record_per_look(desk):
    region = {"x": 10, "y": 20, "width": 300, "height": 200}
    status, body = post(desk, {"for": "screen", "until": "stable", "stable_ms": 100, "timeout_ms": 1000,
                               "poll_ms": 100, "region": region})
    assert (status, body["happened"], body["compared"]) == (200, True, "pixels")
    assert body["still_ms"] >= 100
    assert len(desk.asked) == body["polls"] >= 2
    assert all(asked == ("capture", {
        "fmt": "png", "region_x": 10, "region_y": 20, "region_width": 300, "region_height": 200,
        "desktop_exec": desk.desktop_exec, "detect_env": desk.detect_desktop_env}) for asked in desk.asked)
    assert [record["type"] for record in desk.audited] == ["desktop_wait"]


def test_the_whole_desktop_is_captured_when_no_region_is_given(desk):
    status, body = post(desk, {"for": "screen", "timeout_ms": 1})
    assert (status, body["happened"]) == (200, False)
    assert desk.asked[0] == ("capture", {"fmt": "png", "desktop_exec": desk.desktop_exec,
                                         "detect_env": desk.detect_desktop_env})


def test_a_text_wait_reads_the_screen_for_the_words(desk):
    desk.read = {"ok": True, "matches": [{"text": "Singleplayer"}], "word_count": 9}
    status, body = post(desk, {"for": "text", "text": "singleplayer", "min_confidence": 55,
                               "region": {"x": 1, "y": 2, "width": 3, "height": 4}})
    assert (status, body["happened"], body["match"], body["word_count"]) == (200, True, {"text": "Singleplayer"}, 9)
    assert desk.asked == [("ocr", {
        "query": "singleplayer", "min_confidence": 55, "region_x": 1, "region_y": 2, "region_width": 3,
        "region_height": 4, "capture_screenshot": desk.capture_screenshot, "desktop_exec": desk.desktop_exec,
        "detect_env": desk.detect_desktop_env})]


@pytest.mark.parametrize(("body", "says"), [
    ({"for": "nothing"}, "'for' must be one of: window, screen, text"),
    ({"for": "window", "title": "x", "timeout_ms": 60000}, "'timeout_ms' must be an integer from 1 to 45000"),
    ({"for": "screen", "text": "x"}, "unknown field(s) for a screen wait: text"),
])
def test_a_request_that_cannot_be_planned_is_a_400_and_nothing_is_looked_at(desk, body, says):
    status, answer = post(desk, body)
    assert status == 400
    assert answer["ok"] is False
    assert answer["error"].startswith(says)
    assert desk.asked == []
    assert desk.audited == []
    assert desk.recorded == [{}, {"is_error": True, "count_request": False}]


@pytest.mark.parametrize("sent", [{"data": b"[1, 2]"}, {"data": b"not json"}, {"data": b"true"}])
def test_a_body_that_is_not_an_object_is_a_400(desk, sent):
    status, text = post_raw(desk, None, headers={"Content-Type": "application/json"}, **sent)
    assert status == 400
    assert json.loads(text)["ok"] is False
    assert desk.asked == []


@pytest.mark.parametrize(("body", "broken", "needs"), [
    ({"for": "window", "title": "x"}, ("listing", {"ok": True, "tool": "none", "windows": []}), ["wmctrl", "xdotool"]),
    ({"for": "window", "title": "x", "state": "absent"}, ("listing", {"ok": True, "tool": "none", "windows": []}),
     ["wmctrl", "xdotool"]),
    ({"for": "screen"}, ("shot", {"ok": False, "error": "no tool", "unavailable": ["grim", "scrot"]}),
     ["grim", "scrot"]),
    ({"for": "text", "text": "x"},
     ("read", {"ok": False, "error": "tesseract is not installed", "unavailable": ["tesseract"]}), ["tesseract"]),
])
def test_a_host_that_cannot_look_answers_503_with_what_is_missing(desk, body, broken, needs):
    setattr(desk, *broken)
    status, answer = post(desk, body)
    assert status == 503
    assert (answer["ok"], answer["unavailable"]) == (False, needs)
    assert answer["error"]
    # A missing tool is not this bridge failing: it is not counted as an error, and no wait is noted.
    assert desk.recorded == [{}]
    assert desk.audited == []


@pytest.mark.parametrize(("body", "broken"), [
    ({"for": "window", "title": "x"}, ("listing", {"ok": False, "error": "EnumWindows failed", "windows": []})),
    ({"for": "screen"}, ("shot", {"ok": False, "error": "Windows screenshot failed: BitBlt"})),
    ({"for": "text", "text": "x"}, ("read", {"ok": False, "error": "OCR failed"})),
])
def test_a_look_that_failed_is_a_500_in_the_producers_words(desk, body, broken):
    setattr(desk, *broken)
    status, answer = post(desk, body)
    assert status == 500
    assert (answer["ok"], answer["error"]) == (False, broken[1]["error"])
    assert desk.recorded == [{}, {"is_error": True, "count_request": False}]


def test_a_caller_who_is_not_let_in_starts_no_wait(desk):
    desk.refuse_auth = web.json_response({"error": "unauthorized"}, status=401)
    status, _ = post(desk, {"for": "window", "title": "minecraft"})
    assert status == 401
    assert desk.asked == []


def test_a_paused_desktop_can_still_be_watched(desk):
    """The context here has no `control_check` at all: the handler must not consult one."""
    assert not hasattr(desk, "control_check")
    assert post(desk, {"for": "window", "title": "minecraft"})[0] == 200


def test_the_route_on_a_running_bridge(tmp_path):
    token = secrets.token_hex(8)

    async def go():
        async with running_client(tmp_path, token) as client:
            anonymous = await client.post("/v1/desktop/wait", json={})
            unplanned = await client.post("/v1/desktop/wait", json={"for": "window"}, headers=auth_header(token))
            asked = await client.post("/v1/desktop/wait", headers=auth_header(token),
                                      json={"for": "window", "title": "no-such-window-621", "timeout_ms": 1})
            return anonymous.status, unplanned.status, asked.status, await json_payload(asked)

    anonymous, unplanned, asked, answer = asyncio.run(go())
    assert anonymous in (401, 403)
    assert unplanned == 400
    # A desktop that can list its windows says "not there"; a headless host says what it lacks.
    assert asked in (200, 503)
    if asked == 200:
        assert (answer["ok"], answer["happened"], answer["matches"]) == (True, False, 0)
    else:
        assert answer["unavailable"] == ["wmctrl", "xdotool"]


def test_the_route_is_registered_and_documented():
    assert ("POST", "/v1/desktop/wait", "handle_v1_desktop_wait", "desktop", None) in ROUTES
    ctx = SimpleNamespace(version="test", hostname=lambda: "h", bridge_port=lambda: 8765)
    operation = build_openapi_spec(ctx)["paths"]["/v1/desktop/wait"]["post"]
    assert {"200", "400", "500", "503"} <= set(operation["responses"])
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["required"] == ["for"]
    assert schema["properties"]["for"]["enum"] == ["window", "screen", "text"]
    assert (schema["properties"]["timeout_ms"]["maximum"], schema["properties"]["timeout_ms"]["default"]) == (
        45000, 10000)
    assert (schema["properties"]["poll_ms"]["minimum"], schema["properties"]["poll_ms"]["maximum"]) == (100, 5000)
    answer = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert answer["required"] == ["ok", "happened", "for", "waited_ms", "polls"]


def test_the_tool_and_the_route_take_the_same_fields():
    tool = next(tool for tool in MCP_TOOLS if tool["name"] == "desktop.wait")
    ctx = SimpleNamespace(version="test", hostname=lambda: "h", bridge_port=lambda: 8765)
    route = build_openapi_spec(ctx)["paths"]["/v1/desktop/wait"]["post"]["requestBody"]["content"][
        "application/json"]["schema"]
    assert sorted(tool["inputSchema"]["properties"]) == sorted(route["properties"])
    assert tool["inputSchema"]["required"] == route["required"] == ["for"]
    for name in ("timeout_ms", "poll_ms", "stable_ms", "min_confidence"):
        asked, documented = tool["inputSchema"]["properties"][name], route["properties"][name]
        assert [asked[key] for key in ("minimum", "maximum", "default")] == [
            documented[key] for key in ("minimum", "maximum", "default")]
    assert classify_action("desktop.wait") == "read"


@pytest.fixture(name="bridge")
def _bridge(monkeypatch):
    calls: list[tuple[str, dict]] = []
    answer: dict = {}

    def call(_ctx, path, payload):
        calls.append((path, payload))
        return answer

    monkeypatch.setattr(tool_desktop_wait, "_bridge_call", call)
    return calls, answer


def test_the_tool_passes_its_arguments_on_and_returns_the_answer(bridge):
    calls, answer = bridge
    answer.update({"ok": True, "happened": False, "for": "window", "waited_ms": 1000, "polls": 3, "matches": 0})
    args = {"for": "window", "title": "launcher", "timeout_ms": 1000}
    result = handle_desktop_app_tool("desktop.wait", args, ctx=None)
    assert calls == [("/v1/desktop/wait", args)]
    # Running out of time is an answer, not an error.
    assert "isError" not in result
    assert json.loads(result["content"][0]["text"]) == answer


def test_a_refusal_reaches_the_agent_as_an_error_in_the_bridges_words(bridge):
    _, answer = bridge
    answer.update({"ok": False, "status": 503, "error": "tesseract is not installed", "unavailable": ["tesseract"]})
    result = tool_desktop_wait.handle_desktop_wait_tool("desktop.wait", {"for": "text", "text": "x"}, ctx=None)
    assert result["isError"] is True
    assert json.loads(result["content"][0]["text"]) == answer


def test_the_tool_answers_to_its_own_name_only(bridge):
    calls, _ = bridge
    assert tool_desktop_wait.handle_desktop_wait_tool("desktop.screenshot", {}, ctx=None) is None
    assert tool_desktop_wait.handle_desktop_wait_tool("desktop.waiting", {}, ctx=None) is None
    assert calls == []

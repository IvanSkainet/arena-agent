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

from arena.desktop import ocr, wait, wait_handler
from arena.mcp import tool_desktop_wait
from arena.mcp.tool_desktop_app import handle_desktop_app_tool
from arena.mcp.tool_registry import MCP_TOOLS
from arena.observability.audit_enhanced import classify_action, enrich_event
from arena.public.openapi import build_openapi_spec
from arena.route_registry.registry import ROUTES
from tests._live_bridge import auth_header, json_payload, running_client

GAME = {"id": "7", "title": "Abyssal Ascent - Minecraft", "class": "GLFW30", "geometry": {"width": 800, "height": 600}}
PICTURE = b"BM first"


class Desk:
    """A handler context whose producers remember how they were asked and answer what the test set."""

    #: Set by a test that wants the request turned away at the door.
    refuse_auth: web.Response | None = None
    desktop_exec = object()
    detect_desktop_env = dict
    kwin_windows_via_script = object()

    def __init__(self) -> None:
        """A desktop with one window, a screen that never changes and a reader that finds nothing."""
        self.recorded: list[dict] = []
        self.audited: list[dict] = []
        self.asked: list[tuple[str, dict]] = []
        self.listing: dict = {"ok": True, "tool": "wmctrl", "windows": [GAME]}
        self.shot: dict = {"ok": True, "bytes": PICTURE, "encoding": "png"}
        self.read: dict = {"ok": True, "matches": [], "word_count": 3}
        self.front: dict | None = GAME

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
        return {"captured_region": self._region(kwargs), **self.shot}

    async def ocr_desktop(self, **kwargs):
        self.asked.append(("ocr", kwargs))
        return {"captured_region": self._region(kwargs), **self.read}

    @staticmethod
    def _region(asked: dict) -> dict | None:
        """The region a producer was asked for, as it reports the one it captured."""
        edges = {name[len("region_"):]: value for name, value in asked.items() if name.startswith("region_")}
        return edges or None


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
    assert desk.audited == [{"type": "desktop.wait", "for": "window", "happened": True,
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
    assert [record["type"] for record in desk.audited] == ["desktop.wait"]
    # As the record is written, not as a name typed into the test: the digest counts it among the reads.
    assert enrich_event(desk.audited[0])["action_category"] == "read"


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
    ({"for": "window", "title": "x", "timeout_ms": 60000},
     "body field 'timeout_ms' must be an integer no greater than 45000, received number"),
    ({"for": "screen", "text": "x"}, "unknown field(s) for a screen wait: text"),
])
def test_a_request_that_cannot_be_planned_is_a_400_and_nothing_is_looked_at(desk, body, says):
    status, answer = post(desk, body)
    assert status == 400
    assert answer["ok"] is False
    assert answer["error"].startswith(says)
    assert desk.asked == []
    assert desk.audited == []
    # The caller's mistake is not this bridge failing (#254): the request is counted, an error is not.
    assert desk.recorded == [{}]


def test_a_refused_number_names_its_field_and_what_arrived(desk):
    status, answer = post(desk, {"for": "text", "text": "x", "min_confidence": {"at": "least"}})
    assert status == 400
    assert answer == {"ok": False, "field": "min_confidence", "received": "object",
                      "error": "body field 'min_confidence' must be an integer, received object"}
    status, answer = post(desk, {"for": "screen", "region": {"x": 0, "y": 0, "width": [64], "height": 64}})
    assert (status, answer["field"], answer["received"]) == (400, "region.width", "array")
    assert desk.asked == []


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
    ({"for": "screen", "region": {"x": 0, "y": 0, "width": 9, "height": 9}},
     ("shot", {"ok": True, "bytes": PICTURE, "captured_region": None}), ["pillow"]),
    ({"for": "text", "text": "x", "region": {"x": 0, "y": 0, "width": 9, "height": 9}},
     ("read", {"ok": True, "matches": [], "word_count": 3, "captured_region": None}), ["pillow"]),
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


def test_a_failure_that_gives_no_reason_is_still_named(desk):
    desk.listing = {"ok": False}
    status, answer = post(desk, {"for": "window", "title": "x"})
    assert (status, answer) == (500, {"ok": False, "error": "the desktop could not be looked at"})


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
    answer = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert answer["required"] == ["ok", "happened", "for", "waited_ms", "polls"]


@pytest.mark.parametrize(("body", "names"), [
    ({"for": "window"}, set()),
    ({"for": "window", "title": "x", "nope": 1}, set()),
    ({"for": "window", "title": "x", "timeout_ms": "soon"}, {"field", "received"}),
    ({"for": "screen", "region": {"x": 1, "y": 2, "width": 0, "height": 4}}, {"field", "received"}),
    ([], {"received"}),
    ("window", {"received"}),
])
def test_every_refusal_the_route_gives_fits_the_400_the_document_describes(desk, body, names):
    """Three shapes share the status; a schema that required `field` described one of them."""
    ctx = SimpleNamespace(version="test", hostname=lambda: "h", bridge_port=lambda: 8765)
    described = build_openapi_spec(ctx)["paths"]["/v1/desktop/wait"]["post"]["responses"]["400"]
    schema = described["content"]["application/json"]["schema"]
    assert sorted(schema["required"]) == ["error", "ok"]
    assert {"field", "received"} <= set(schema["properties"])
    assert "JSON object" in described["description"]
    status, answer = post(desk, body)
    assert status == 400
    assert set(schema["required"]) <= set(answer)
    assert set(answer) - {"ok", "error"} == names
    assert set(answer) <= set(schema["properties"])
    if names:
        assert answer["received"] in schema["properties"]["received"]["enum"]


def test_the_tool_is_listed_and_only_reads():
    tool = next(tool for tool in MCP_TOOLS if tool["name"] == "desktop.wait")
    assert tool["inputSchema"]["required"] == ["for"]
    assert "running out of time is not an error" in tool["description"]
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


def test_a_title_in_another_alphabet_reaches_the_agent_as_written(bridge):
    _, answer = bridge
    answer.update({"ok": True, "happened": True, "for": "window", "window": {"title": "Блокнот"}})
    result = tool_desktop_wait.handle_desktop_wait_tool("desktop.wait", {"for": "window", "title": "x"}, ctx=None)
    assert "Блокнот" in result["content"][0]["text"]


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


def test_the_real_reader_says_which_region_its_picture_shows(monkeypatch):
    """`ocr_desktop` hands on the capture's `captured_region`, which is how a text wait knows the crop happened."""
    async def capture(**_kwargs):
        return {"ok": True, "bytes": b"picture", "crop_region": {"x": 1, "y": 2, "width": 3, "height": 4},
                "captured_region": None, "tool": "grim"}

    async def run(_command, timeout):
        assert timeout
        return {"ok": True, "stdout": ""}

    monkeypatch.setattr(ocr, "find_tesseract", lambda: "tesseract")
    result = asyncio.run(ocr.ocr_desktop(query="x", region_x=1, region_y=2, region_width=3, region_height=4,
                                         capture_screenshot=capture, desktop_exec=run, detect_env=dict))
    assert result["ok"] is True
    assert result["crop_region"] == {"x": 1, "y": 2, "width": 3, "height": 4}
    assert "captured_region" in result
    assert result["captured_region"] is None


TSV = "\n".join(["level\tpage\tblock\tpar\tline\tword\tleft\ttop\twidth\theight\tconf\ttext",
                 "5\t1\t1\t1\t1\t1\t10\t20\t30\t12\t0\tghost",
                 "5\t1\t1\t1\t1\t2\t50\t20\t30\t12\t39.5\tfaint",
                 "5\t1\t1\t1\t1\t3\t90\t20\t30\t12\t40\tclear"])


@pytest.mark.parametrize(("asked", "kept"), [
    ({"min_confidence": 0}, ["ghost", "faint", "clear"]),
    ({"min_confidence": None}, ["clear"]),
    ({}, ["clear"]),
    ({"min_confidence": -5}, ["ghost", "faint", "clear"]),
    ({"min_confidence": 40}, ["clear"]),
    ({"min_confidence": 41}, []),
])
def test_the_real_reader_keeps_words_at_the_confidence_asked_for_and_zero_means_zero(monkeypatch, asked, kept):
    """`min_confidence: 0` is in the range a wait documents; the reader used to read it as 40."""
    async def capture(**_kwargs):
        return {"ok": True, "bytes": b"picture"}

    async def run(_command, timeout):
        assert timeout
        return {"ok": True, "stdout": TSV}

    monkeypatch.setattr(ocr, "find_tesseract", lambda: "tesseract")
    result = asyncio.run(ocr.ocr_desktop(capture_screenshot=capture, desktop_exec=run, detect_env=dict, **asked))
    assert [word["text"] for word in result["words"]] == kept


def test_the_real_reader_puts_the_words_of_a_region_where_they_are_on_the_desktop(monkeypatch):
    async def capture(**_kwargs):
        return {"ok": True, "bytes": b"picture"}

    async def run(_command, timeout):
        assert timeout
        return {"ok": True, "stdout": TSV}

    monkeypatch.setattr(ocr, "find_tesseract", lambda: "tesseract")
    read = {"capture_screenshot": capture, "desktop_exec": run, "detect_env": dict}
    moved = asyncio.run(ocr.ocr_desktop(region_x=100, region_y=200, region_width=300, region_height=50, **read))
    whole = asyncio.run(ocr.ocr_desktop(**read))
    assert [(word["bbox"]["x"], word["bbox"]["y"]) for word in whole["words"]] == [(90, 20)]
    assert [(word["bbox"]["x"], word["bbox"]["y"]) for word in moved["words"]] == [(190, 220)]
    assert moved["words"][0]["center"]["x"] - whole["words"][0]["center"]["x"] == 100
    assert moved["words"][0]["center"]["y"] - whole["words"][0]["center"]["y"] == 200
    # Only one of the two corners given: nothing is moved.
    half = asyncio.run(ocr.ocr_desktop(region_x=100, **read))
    assert half["words"][0]["bbox"] == whole["words"][0]["bbox"]


def test_a_listing_that_hangs_is_given_up_on_and_answered_as_a_failure_of_the_look(desk, monkeypatch):
    async def hangs(**_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(wait_handler, "list_desktop_windows", hangs)
    monkeypatch.setattr(wait, "LOOK_GRACE_MS", 40)
    status, body = post(desk, {"for": "window", "title": "minecraft", "timeout_ms": 1})
    assert status == 500
    assert body["ok"] is False
    assert "still running 40 ms after the time to wait was up" in body["error"]
    assert "unavailable" not in body
    assert desk.audited == []


def test_a_class_asked_of_a_window_list_without_classes_is_a_failure_and_not_a_wrong_answer(desk):
    desk.listing = {"ok": True, "tool": "wmctrl", "windows": [{"id": "0x1", "title": "Abyssal Ascent - Minecraft"}]}
    status, body = post(desk, {"for": "window", "class": "glfw", "state": "absent", "timeout_ms": 1})
    assert status == 500
    assert "'class' cannot be matched here" in body["error"]
    assert post(desk, {"for": "window", "title": "minecraft", "timeout_ms": 1})[1]["happened"] is True

"""#620: a desktop MCP tool passes on what the route said when it refused."""
# `desktop.find_text` over MCP returned "ERROR: HTTPError: HTTP Error 503:
# Service Unavailable" while the route had answered `503 {"error": "tesseract
# is not installed", "unavailable": ["tesseract"]}`. The reason and the list of
# missing tools never reached the agent.
from __future__ import annotations

import io
import json
import secrets
import urllib.error
import urllib.parse
from types import SimpleNamespace

import pytest

from arena.mcp.desktop_refusal import REFUSAL_LIMIT, answers_refusals, bridge_refusal
from arena.mcp.tool_desktop import handle_desktop_tool
from arena.mcp.tool_desktop_app import handle_desktop_app_tool
from arena.mcp.tool_desktop_input import handle_desktop_input_tool
from arena.mcp.tool_registry import MCP_TOOLS

_NO_TESSERACT = {"ok": False, "error": "tesseract is not installed", "unavailable": ["tesseract"]}
_DISPATCHERS = (handle_desktop_tool, handle_desktop_input_tool, handle_desktop_app_tool)
_DESKTOP_TOOLS = sorted(tool["name"] for tool in MCP_TOOLS if tool["name"].startswith(("desktop.", "desktop_app.")))


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(app_config=lambda: {"port": 1, "token": secrets.token_hex(8)})


def _call(name: str, args: dict) -> dict | None:
    for dispatch in _DISPATCHERS:
        result = dispatch(name, args, ctx=_ctx())
        if result is not None:
            return result
    return None


def _words(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


class _Bridge:
    """Stands in for `urlopen`: every request is refused with the same status and body."""

    def __init__(self, status: int, body: bytes):
        """Remember what to answer; `asked` collects the URLs that were requested."""
        self.status, self.body, self.asked = status, body, []

    def __call__(self, request, timeout):
        self.asked.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, self.status, "refused", {}, io.BytesIO(self.body))


@pytest.fixture(name="refusing")
def _refusing(monkeypatch):
    bridge = _Bridge(503, json.dumps(_NO_TESSERACT).encode())
    monkeypatch.setattr("urllib.request.urlopen", bridge)
    return bridge


def test_the_refusal_from_the_issue_reaches_the_agent(refusing):
    result = _call("desktop.find_text", {"query": "Play"})
    assert result["isError"] is True
    assert _words(result) == {**_NO_TESSERACT, "status": 503, "route": "/v1/desktop/find_text"}
    assert refusing.asked == ["http://127.0.0.1:1/v1/desktop/find_text"]


def test_there_are_desktop_tools_to_sweep():
    assert {"desktop.find_text", "desktop.key", "desktop.windows", "desktop_app.focus"} <= set(_DESKTOP_TOOLS)


@pytest.mark.parametrize("name", _DESKTOP_TOOLS)
def test_no_desktop_tool_hides_a_refusal_behind_the_name_of_an_exception(name, refusing):
    """Every desktop tool, whichever module dispatches it and however many calls it makes."""
    result = _call(name, {"query": "x", "title": "x", "text": "x", "key": "a", "x": 1, "y": 1,
                          "steps": [], "require_active_title": "x"})
    assert result is not None, f"{name} is registered and nothing dispatches it"
    assert refusing.asked, f"{name} answered without asking the bridge, so this sweep says nothing about it"
    assert result["isError"] is True
    assert _words(result)["error"] == "tesseract is not installed"
    assert _words(result)["unavailable"] == ["tesseract"]
    assert _words(result)["status"] == 503


def test_a_tool_that_makes_several_calls_says_which_route_refused(refusing):
    words = _words(_call("desktop_app.focus", {"title": "Editor"}))
    assert words["route"] == "/v1/desktop/windows"
    assert len(refusing.asked) == 1


class _Answer(io.BytesIO):
    status = 200


def test_a_refusal_after_a_call_that_was_answered_names_the_later_route(monkeypatch):
    """The window list is answered, the focus is refused: the refusal is the focus route's, not the first one asked."""
    asked: list[str] = []

    def bridge(request, timeout):
        path = urllib.parse.urlsplit(request.full_url).path
        asked.append(path)
        if path == "/v1/desktop/windows":
            window = {"id": "7", "title": "Editor", "geometry": {"x": 0, "y": 0, "width": 800, "height": 600}}
            return _Answer(json.dumps({"ok": True, "windows": [window]}).encode())
        raise urllib.error.HTTPError(request.full_url, 409, "refused", {}, io.BytesIO(b'{"error": "window_gone"}'))

    monkeypatch.setattr("urllib.request.urlopen", bridge)
    result = _call("desktop_app.focus", {"title": "Editor"})
    assert asked == ["/v1/desktop/windows", "/v1/desktop/focus"]
    assert result["isError"] is True
    assert _words(result) == {"error": "window_gone", "ok": False, "status": 409, "route": "/v1/desktop/focus"}


def test_a_refusal_too_large_to_be_one_is_not_read_whole(monkeypatch):
    class _Counting(io.BytesIO):
        taken = 0

        def read(self, size=-1):
            data = super().read(size)
            type(self).taken += len(data)
            return data

    body = _Counting(b'{"error": "' + b"x" * 1_000_000 + b'"}')
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: (_ for _ in ()).throw(
        urllib.error.HTTPError(request.full_url, 500, "refused", {}, body)))
    result = _call("desktop.windows", {})
    words = _words(result)
    assert result["isError"] is True
    assert _Counting.taken == REFUSAL_LIMIT + 1
    assert words["error"] == "the bridge answered HTTP 500 with a body over 65536 bytes, which was not read"
    assert words["detail"] == '{"error": "' + "x" * 489
    assert words["status"] == 500


def test_the_limit_is_far_above_any_refusal_and_far_below_what_hurts():
    assert REFUSAL_LIMIT == 65536


def test_a_body_of_exactly_the_limit_that_is_not_json_is_not_called_too_large(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _Bridge(502, b"<" * REFUSAL_LIMIT))
    assert _words(_call("desktop.windows", {}))["error"] == "the bridge answered HTTP 502"


def test_a_body_that_is_not_text_is_still_reported(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _Bridge(502, b"\xff\xfe upstream"))
    assert _words(_call("desktop.windows", {}))["detail"] == "\ufffd\ufffd upstream"


def test_a_refusal_without_an_address_has_an_empty_route_not_a_made_up_one():
    refusal = bridge_refusal(urllib.error.HTTPError(None, 500, "refused", {}, io.BytesIO(b'{"error": "x"}')))
    assert refusal == {"error": "x", "ok": False, "status": 500, "route": ""}


def test_the_wrapped_dispatchers_keep_their_names():
    assert [dispatch.__name__ for dispatch in _DISPATCHERS] == [
        "handle_desktop_tool", "handle_desktop_input_tool", "handle_desktop_app_tool"]


def test_a_refusal_of_exactly_the_limit_is_still_read_as_what_it_is(monkeypatch):
    padding = REFUSAL_LIMIT - len(b'{"error": ""}')
    monkeypatch.setattr("urllib.request.urlopen", _Bridge(503, b'{"error": "' + b"x" * padding + b'"}'))
    assert _words(_call("desktop.windows", {}))["error"] == "x" * padding


def test_a_refusal_that_is_not_json_still_says_what_happened(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _Bridge(502, b"<html>upstream</html>"))
    result = _call("desktop.windows", {})
    assert result["isError"] is True
    assert _words(result) == {"error": "the bridge answered HTTP 502", "detail": "<html>upstream</html>",
                              "ok": False, "status": 502, "route": "/v1/desktop/windows"}


def test_a_refusal_that_is_json_but_not_an_object_is_treated_the_same(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _Bridge(500, b"[1, 2]"))
    result = _call("desktop.key", {"key": "a"})
    words = _words(result)
    assert result["isError"] is True
    assert words["ok"] is False
    assert "500" in words["error"]


def test_what_the_route_says_about_itself_is_not_overwritten(monkeypatch):
    body = {"ok": False, "error": "paused", "status": "paused-by-owner", "route": "elsewhere"}
    monkeypatch.setattr("urllib.request.urlopen", _Bridge(403, json.dumps(body).encode()))
    assert _words(_call("desktop.click", {"x": 1, "y": 1})) == body


def test_an_answer_is_still_an_answer(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: _Answer(b'{"ok": true, "windows": []}'))
    result = _call("desktop.windows", {})
    assert "isError" not in result
    assert _words(result) == {"ok": True, "windows": []}


def test_a_failure_that_is_not_a_refusal_is_not_dressed_up_as_one(monkeypatch):
    """Only an HTTP answer is a refusal; a bridge that is not there stays the error it is."""
    def nobody_home(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", nobody_home)
    with pytest.raises(urllib.error.URLError):
        _call("desktop.windows", {})


def test_a_dispatcher_still_passes_on_a_name_that_is_not_its_own():
    assert handle_desktop_tool("browser.open", {}, ctx=_ctx()) is None
    assert answers_refusals(lambda name, args, *, ctx: None)("x", {}, ctx=None) is None

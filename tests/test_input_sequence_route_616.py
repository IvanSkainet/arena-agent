"""POST /v1/desktop/sequence and MCP `desktop.sequence`: the route, its refusals, the tool (#616)."""
# The driver is a recorder; the one test that starts a bridge gets a 501 or a
# guard refusal from it, never input.

from __future__ import annotations

import asyncio
import inspect
import io
import json
import re
import secrets
import sys
import threading
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from arena.desktop import input_sequence_handler
from arena.desktop.input_sequence import (
    MAX_TOTAL_MS,
)
from arena.extension_bridge.policy import classify_tool_risk
from arena.mcp import tool_desktop_sequence
from arena.mcp.tool_desktop_input import handle_desktop_input_tool
from arena.mcp.tool_registry import MCP_TOOLS
from arena.public.openapi import build_openapi_spec
from arena.route_registry.registry import ROUTES
from tests._input_sequence_support import Recorder, handler_ctx, post, post_raw
from tests._live_bridge import auth_header, json_payload, running_client


@pytest.fixture(name="driver")
def _driver(monkeypatch) -> Recorder:
    driver = Recorder()
    monkeypatch.setattr(input_sequence_handler, "sequence_driver", lambda env: driver)
    return driver


def test_the_route_runs_a_sequence_and_reports_it(driver):
    ctx, recorded = handler_ctx()
    status, body = post(ctx, {"require_active_title": "game", "steps": [
        {"do": "key_down", "key": "w"}, {"do": "wait", "ms": 30}, {"do": "key_up", "key": "w"}]})
    assert status == 200
    assert body["ok"] is True
    assert body["steps_done"] == 3
    assert driver.events == [("key_down", "w"), ("key_up", "w")]
    assert {"agent_action": True} in recorded


@pytest.mark.parametrize("body", [
    {"steps": [{"do": "tap", "key": "w"}]},
    {"steps": [{"do": "tap", "key": "w"}], "require_active_title": "   "},
    {"steps": [{"do": "tap", "key": "w"}], "require_active_title": 7},
])
def test_a_sequence_that_does_not_name_its_window_is_refused(driver, body):
    ctx, _ = handler_ctx()
    status, answer = post(ctx, body)
    assert status == 400
    assert "require_active_title" in answer["error"]
    assert driver.events == []


def test_a_bad_step_is_a_400_that_names_the_step(driver):
    ctx, recorded = handler_ctx()
    status, body = post(ctx, {"require_active_title": "game", "steps": [
        {"do": "tap", "key": "w"}, {"do": "tap", "key": "hyper"}]})
    assert status == 400
    assert body == {"ok": False, "error": "step 1: unknown key 'hyper'", "step": 1}
    assert driver.events == []
    assert {"agent_action": True} not in recorded


def test_the_wrong_window_is_a_409(driver):
    driver.title = "Terminal"
    ctx, _ = handler_ctx()
    status, body = post(ctx, {"require_active_title": "game", "steps": [{"do": "tap", "key": "w"}]})
    assert status == 409
    assert body["error"] == "input_guard_failed"
    assert body["active_title"] == "Terminal"
    assert driver.events == []


def test_a_lease_paused_mid_sequence_is_a_403_and_releases(driver):
    calls = {"n": 0}

    def control():
        calls["n"] += 1
        if calls["n"] > 2:
            return {"ok": False, "error": "control_paused", "status": "paused", "reason": None}
        return None

    ctx, _ = handler_ctx(control=control)
    status, body = post(ctx, {"require_active_title": "game", "steps": [
        {"do": "key_down", "key": "w"}, {"do": "wait", "ms": 200}, {"do": "key_up", "key": "w"}]})
    assert status == 403
    assert body["error"] == "control_paused"
    assert driver.events == [("key_down", "w"), ("key_up", "w")]


def test_a_desktop_without_a_driver_says_so_instead_of_pretending():
    ctx, _ = handler_ctx(env={"has_win32_input": False, "has_xdotool": True})
    status, body = post(ctx, {"require_active_title": "game", "steps": [{"do": "tap", "key": "w"}]})
    assert status == 501
    assert body["ok"] is False
    assert "Windows" in body["error"]


def test_a_refused_plan_with_no_step_at_fault_has_no_step_field(driver):
    """The schema says `step` is an integer; `null` was what an empty list got."""
    ctx, _ = handler_ctx()
    status, body = post(ctx, {"require_active_title": "game", "steps": []})
    assert status == 400
    assert "step" not in body
    status, body = post(ctx, {"require_active_title": "game", "steps": [{"do": "tap", "key": "hyper"}]})
    assert status == 400
    assert body["step"] == 0


class _SlowDriver(Recorder):
    """Blocks in its first key press until the test lets it go on."""

    def __init__(self) -> None:
        """Nothing pressed, nothing allowed to finish yet."""
        super().__init__()
        self.pressing = threading.Event()
        self.go_on = threading.Event()

    def key_down(self, name: str) -> None:
        self.pressing.set()
        assert self.go_on.wait(10), "the test never let the first sequence finish"
        super().key_down(name)


def test_a_second_sequence_is_refused_while_the_first_is_still_running(monkeypatch):
    """Two at once interleave, and each lets go of the keys the other still holds."""
    slow = _SlowDriver()
    monkeypatch.setattr(input_sequence_handler, "sequence_driver", lambda env: slow)
    ctx, _ = handler_ctx()
    body = {"require_active_title": "game", "steps": [{"do": "key_down", "key": "w"}]}

    async def go():
        app = web.Application()
        app.router.add_post("/v1/desktop/sequence", input_sequence_handler.make_desktop_sequence_handler(ctx))
        async with TestClient(TestServer(app)) as client:
            first = asyncio.ensure_future(client.post("/v1/desktop/sequence", json=body))
            await asyncio.get_running_loop().run_in_executor(None, slow.pressing.wait, 10)
            second = await client.post("/v1/desktop/sequence", json=body)
            refused = second.status, await second.json()
            slow.go_on.set()
            finished = await first
            third = await client.post("/v1/desktop/sequence", json=body)
            return refused, finished.status, third.status

    refused, first_status, third_status = asyncio.run(go())
    assert refused[0] == 409
    assert refused[1]["error"] == "sequence_in_progress"
    assert first_status == 200
    assert third_status == 200, "the lock was not released when the first sequence ended"


def test_a_run_that_blows_up_still_lets_the_next_one_in(driver, monkeypatch):
    def explode(steps, driver, guard):
        raise RuntimeError("not an input failure")

    ctx, _ = handler_ctx()
    body = {"require_active_title": "game", "steps": [{"do": "tap", "key": "w"}]}
    with monkeypatch.context() as broken:
        broken.setattr(input_sequence_handler, "run_sequence", explode)
        status, _ = post_raw(ctx, body)
    assert status == 500
    status, answer = post(ctx, body)
    assert status == 200
    assert answer["ok"] is True


def test_a_host_that_fell_behind_is_a_500_and_says_so(driver, monkeypatch):
    def overran(steps, driver, guard):
        return {"ok": False, "error": "input_overran", "message": "key:w has been down longer than 15000 ms"}

    monkeypatch.setattr(input_sequence_handler, "run_sequence", overran)
    ctx, recorded = handler_ctx()
    status, body = post(ctx, {"require_active_title": "game", "steps": [{"do": "tap", "key": "w"}]})
    assert status == 500
    assert body["error"] == "input_overran"
    assert {"is_error": True, "count_request": False} in recorded


def test_the_route_is_registered_and_guarded_on_a_running_bridge(tmp_path: Path):
    """Through the real application: auth first, then the window guard or the honest 501."""
    token = secrets.token_hex(8)

    async def go():
        async with running_client(tmp_path, token) as client:
            anonymous = await client.post("/v1/desktop/sequence", json={})
            unnamed = await client.post("/v1/desktop/sequence", json={"steps": []}, headers=auth_header(token))
            nobody = await client.post(
                "/v1/desktop/sequence", headers=auth_header(token),
                json={"require_active_title": "no-such-window-616", "steps": [{"do": "wait", "ms": 1}]})
            return anonymous.status, unnamed.status, nobody.status, await json_payload(nobody)

    anonymous, unnamed, nobody, answer = asyncio.run(go())
    assert anonymous in (401, 403)
    assert unnamed == 400
    # On Windows the guard refuses before any input; elsewhere there is no driver.
    assert nobody == (409 if sys.platform == "win32" else 501)
    assert answer["ok"] is False


def test_the_document_tells_a_client_about_every_way_the_route_refuses():
    ctx = SimpleNamespace(version="test", hostname=lambda: "h", bridge_port=lambda: 8765)
    operation = build_openapi_spec(ctx)["paths"]["/v1/desktop/sequence"]["post"]
    assert {"200", "400", "403", "409", "500", "501"} <= set(operation["responses"])
    refused = operation["responses"]["400"]["content"]["application/json"]["schema"]["properties"]
    assert {"ok", "error", "step", "received"} <= set(refused)
    body = operation["requestBody"]["content"]["application/json"]["schema"]
    assert body["required"] == ["steps", "require_active_title"]


def test_the_route_is_in_the_registry():
    assert ("POST", "/v1/desktop/sequence", "handle_v1_desktop_sequence", "desktop", None) in ROUTES


# ---------------------------------------------------------------------
# 5. the MCP tool
# ---------------------------------------------------------------------
def test_the_tool_is_listed_and_needs_approval():
    tool = next(tool for tool in MCP_TOOLS if tool["name"] == "desktop.sequence")
    assert tool["inputSchema"]["required"] == ["steps", "require_active_title"]
    assert classify_tool_risk("desktop.sequence") == "dangerous"


def test_the_tool_posts_the_sequence_and_returns_the_bridge_s_answer(monkeypatch):
    seen = {}

    def bridge_call(ctx, path, payload):
        seen.update(path=path, payload=payload)
        return {"ok": True, "steps_done": 2}

    monkeypatch.setattr(tool_desktop_sequence, "_bridge_call", bridge_call)
    args = {"require_active_title": "game", "steps": [{"do": "key_down", "key": "w"}, {"do": "wait", "ms": 400}]}
    result = tool_desktop_sequence.handle_desktop_sequence_tool("desktop.sequence", args, ctx=None)
    assert seen == {"path": "/v1/desktop/sequence", "payload": args}
    assert json.loads(result["content"][0]["text"]) == {"ok": True, "steps_done": 2}
    assert "isError" not in result
    assert tool_desktop_sequence.handle_desktop_sequence_tool("desktop.key", {}, ctx=None) is None


def test_the_tool_outwaits_the_longest_sequence():
    """The helper's timeout is a literal in another module; the limit here must stay under it."""
    waits = [int(found) for found in re.findall(r"timeout=(\d+)", inspect.getsource(tool_desktop_sequence._bridge_call))]
    assert waits, "the helper no longer states its timeout where this test can read it"
    assert MAX_TOTAL_MS / 1000 + 10 <= min(waits)


def test_the_dispatcher_reaches_the_tool_through_the_desktop_input_handler(monkeypatch):
    """`arena/mcp/tools.py` lists one handler for desktop input; the sequence tool hangs off it."""
    monkeypatch.setattr(tool_desktop_sequence, "_bridge_call", lambda ctx, path, payload: {"ok": True})
    assert handle_desktop_input_tool("desktop.sequence", {"steps": []}, ctx=None)["content"][0]["text"] == '{"ok": true}'
    assert handle_desktop_input_tool("desktop.no_such_tool", {}, ctx=None) is None


def test_the_tool_passes_a_refusal_on_in_the_bridge_s_own_words(monkeypatch):
    """Not "HTTP Error 409: Conflict": the agent has to learn which window was in front."""
    refusal = {"ok": False, "error": "input_guard_failed", "active_title": "Terminal", "steps_done": 0, "status": 409}
    monkeypatch.setattr(tool_desktop_sequence, "_bridge_call", lambda ctx, path, payload: dict(refusal))
    result = tool_desktop_sequence.handle_desktop_sequence_tool(
        "desktop.sequence", {"steps": [], "require_active_title": "game"}, ctx=None)
    assert result["isError"] is True
    assert json.loads(result["content"][0]["text"]) == refusal


def test_a_refusal_reaches_the_tool_from_a_real_http_error(monkeypatch):
    """Through the helper itself: the body the route wrote survives the HTTPError."""
    body = json.dumps({"ok": False, "error": "input_guard_failed", "active_title": "Terminal"}).encode()

    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 409, "Conflict", {}, io.BytesIO(body))

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    ctx = SimpleNamespace(app_config=lambda: {"port": 1, "token": secrets.token_hex(8)})
    result = tool_desktop_sequence.handle_desktop_sequence_tool(
        "desktop.sequence", {"steps": [], "require_active_title": "game"}, ctx=ctx)
    answer = json.loads(result["content"][0]["text"])
    assert result["isError"] is True
    assert answer["error"] == "input_guard_failed"
    assert answer["active_title"] == "Terminal"

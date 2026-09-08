"""GET /v1/events keeps to the document it publishes (#258, step 2).

The second batch of the fuzzing gate turns on `status_code_conformance`,
which compares every answer against the operation's documented codes. This
operation had one documented code, 200, and never sent it: a plain GET got
aiohttp's own plain-text 400 ("No WebSocket UPGRADE hdr"), a handshake with
missing headers got a different plain-text 400 ("Unsupported version"), and
a request with no credential got a *successful* handshake followed by an
`unauthorized` frame.

That last one is the part worth having a test for on its own: an anonymous
caller was given a live socket, the failed-auth throttle never saw the
attempt, and any client reading status codes was told it had succeeded.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

from tests._live_bridge import build_app

TOKEN = "events-contract-token"


@pytest.fixture()
def bridge(tmp_path: Path):
    """The real application, on a real socket, because this is about HTTP.

    A `TestClient` would answer the handshake in process and hide exactly
    the header handling under test.
    """
    async def _run(check):
        app = build_app(tmp_path, TOKEN)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        try:
            async with aiohttp.ClientSession() as session:
                return await check(session, f"http://127.0.0.1:{port}")
        finally:
            await runner.cleanup()

    def run(check):
        return asyncio.run(_run(check))

    return run


def test_a_plain_get_is_426_with_the_usual_json_shape(bridge) -> None:
    """Not aiohttp's plain-text 400: the same error shape as every other refusal."""
    async def check(session, base):
        async with session.get(f"{base}/v1/events",
                               headers={"Authorization": f"Bearer {TOKEN}"}) as resp:
            return resp.status, resp.headers.get("Upgrade"), json.loads(await resp.text())

    status, upgrade, body = bridge(check)
    assert status == 426
    assert upgrade == "websocket"
    assert body["ok"] is False
    assert body["upgrade"] == "websocket"
    assert "WebSocket" in body["error"]


def test_a_half_finished_handshake_is_also_426(bridge) -> None:
    """`Upgrade: websocket` without the key or version headers.

    aiohttp raises its own 400 from `prepare()` for these, which is the
    same undocumented answer wearing a different hat, so the handler
    catches it and gives the documented one with the reason attached.
    """
    async def check(session, base):
        async with session.get(
                f"{base}/v1/events",
                headers={"Authorization": f"Bearer {TOKEN}",
                         "Upgrade": "websocket", "Connection": "Upgrade"}) as resp:
            return resp.status, json.loads(await resp.text())

    status, body = bridge(check)
    assert status == 426
    assert body["ok"] is False


def test_no_credential_is_a_401_before_any_upgrade(bridge) -> None:
    """The refusal is an HTTP status, not a frame on a socket that opened anyway."""
    async def check(session, base):
        async with session.get(
                f"{base}/v1/events",
                headers={"Upgrade": "websocket", "Connection": "Upgrade"}) as resp:
            return resp.status, json.loads(await resp.text())

    status, body = bridge(check)
    assert status == 401
    assert body["ok"] is False
    assert body["error"] == "unauthorized"


def test_a_real_handshake_still_opens_the_stream(bridge) -> None:
    """The guards are about malformed requests; a correct one is untouched."""
    async def check(session, base):
        async with session.ws_connect(
                f"{base}/v1/events",
                headers={"Authorization": f"Bearer {TOKEN}"}) as ws:
            hello = await asyncio.wait_for(ws.receive_json(), timeout=10)
            await ws.close()
            return hello

    hello = bridge(check)
    assert hello["type"] == "connected"


def test_connection_header_may_be_a_list(bridge) -> None:
    """`Connection: keep-alive, Upgrade` is what browsers and proxies send.

    A membership test rather than an equality one, or every real client
    would be told to upgrade something it already upgraded.
    """
    async def check(session, base):
        async with session.ws_connect(
                f"{base}/v1/events",
                headers={"Authorization": f"Bearer {TOKEN}",
                         "Connection": "keep-alive, Upgrade"}) as ws:
            hello = await asyncio.wait_for(ws.receive_json(), timeout=10)
            await ws.close()
            return hello

    assert bridge(check)["type"] == "connected"


def test_the_handshake_headers_are_matched_case_insensitively(bridge) -> None:
    """RFC 6455 4.2.1 says both values are ASCII case-insensitive.

    `_is_websocket_upgrade` lowercases before comparing, so `WebSocket` and
    `keep-alive, UPGRADE` are a valid handshake; the document used to say
    `enum: ["websocket"]`, which told generated clients otherwise
    (coderabbit).
    """
    async def check(session, base):
        async with session.ws_connect(
                f"{base}/v1/events",
                headers={"Authorization": f"Bearer {TOKEN}",
                         "Upgrade": "WebSocket",
                         "Connection": "keep-alive, UPGRADE"}) as ws:
            hello = await asyncio.wait_for(ws.receive_json(), timeout=10)
            await ws.close()
            return hello

    assert bridge(check)["type"] == "connected"


def test_the_document_does_not_pin_either_header_to_one_spelling() -> None:
    """The document has to agree with the case-insensitive match above."""
    from types import SimpleNamespace

    from arena.public.openapi import build_openapi_spec

    spec = build_openapi_spec(
        SimpleNamespace(version="t", hostname=lambda: "h", bridge_port=lambda: 8765))
    params = {p["name"]: p for p in spec["paths"]["/v1/events"]["get"]["parameters"]}
    for name in ("Upgrade", "Connection"):
        assert "enum" not in params[name]["schema"], f"{name} is pinned to one spelling"
        assert params[name].get("description"), f"{name} states no requirement"


def test_a_malformed_frame_is_never_a_command() -> None:
    """Everything a client can send that is not `{"command": "..."}`.

    The deep-nesting case is the one that bit: `json.loads` raises
    RecursionError rather than ValueError there, and an uncaught one would
    end a stream on input a client controls (cubic).
    """
    import sys

    from arena.events.handlers import _client_command

    assert _client_command('{"command": "ping"}') == "ping"
    assert _client_command("null") is None
    assert _client_command("[1, 2, 3]") is None
    assert _client_command("not json at all") is None
    assert _client_command(b"\xff\xfe") is None
    assert _client_command('{"command": 7}') is None
    assert _client_command("{}") is None
    # A deeply nested frame is answered, not raised through. Which
    # exception the parser picks is CPython's business and it changed in
    # 3.14 (the old assertion demanded RecursionError and went red there),
    # so this half only pins our side: no escape, no command.
    limit = sys.getrecursionlimit()
    deep = "[" * (limit * 24) + "]" * (limit * 24)
    assert _client_command(deep) is None


def test_a_parser_recursion_error_is_caught_not_raised(monkeypatch) -> None:
    """The RecursionError arm of the catch, pinned without CPython's help.

    Real deep input only raises RecursionError on some interpreter
    versions, so the arm is exercised directly: if it were dropped from
    the `except` clause this call would raise instead of answering None.
    """
    from arena.events import handlers as events_handlers

    def explode(_raw: object) -> object:
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(events_handlers.json, "loads", explode)

    assert events_handlers._client_command('{"command": "ping"}') is None


def test_an_event_that_will_not_serialize_does_not_kill_the_stream(bridge) -> None:
    """One bad payload is one dropped event, not a dead subscriber.

    `emit_event` puts whatever it is given on the queue without checking
    that it can be encoded, so an event carrying a `datetime` used to end
    the forwarder while the socket stayed open: the subscriber received
    nothing further and never learned why (coderabbit).
    """
    from datetime import datetime

    from arena.events.runtime import EVENT_SUBSCRIBERS

    async def check(session, base):
        async with session.ws_connect(
                f"{base}/v1/events",
                headers={"Authorization": f"Bearer {TOKEN}"}) as ws:
            await asyncio.wait_for(ws.receive_json(), timeout=10)  # the welcome
            for _ in range(50):  # the subscriber registers on the server side
                if EVENT_SUBSCRIBERS:
                    break
                await asyncio.sleep(0.05)
            assert EVENT_SUBSCRIBERS, "the stream never subscribed"
            queue = EVENT_SUBSCRIBERS[-1]
            queue.put_nowait({"type": "unserializable", "data": {"when": datetime.now()}})
            queue.put_nowait({"type": "after", "data": {"ok": True}})
            received = await asyncio.wait_for(ws.receive_json(), timeout=10)
            await ws.close()
            return received

    received = bridge(check)
    assert received["type"] == "after", (
        f"the event after the unserializable one never arrived: {received}")

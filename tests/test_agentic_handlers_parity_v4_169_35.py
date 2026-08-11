"""v4.169.35 -- arena.agentic.handlers parity tests (mutation-driven).

Fast, isolated tests for `handle_v1_react` and `handle_v1_reflect`:
* Invalid JSON decoding returns 400 with exact error format;
* Missing / whitespace goal returns 400 "missing goal";
* Parameter extraction and default values for react (context, constraints, max_iterations=4, memory_profile, url);
* Parameter extraction and default values for reflect (goal, run, notes, outcome);
* Audit log event payload validation for both handlers;
* Auth enforcement verification via `@authed(ctx)`;
* Immutability enforcement of `AgenticHandlers` dataclass (frozen=True).
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.agentic.handlers import make_agentic_handlers  # noqa: E402


def _cors_json_response(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


class _MockContext:
    def __init__(self):
        self.auth_calls = []
        self.audit_events = []
        self.react_calls = []
        self.reflect_calls = []
        self.react_result = {"ok": True, "iterations": [1, 2], "memory_profile": "browser"}
        self.reflect_result = {"ok": True, "goal": "target goal", "confidence": "high"}

    def require_auth(self, request):
        self.auth_calls.append(request)
        return None

    def record_request(self, *args, **kwargs):
        pass

    def cors_json_response(self, data, status=200):
        return _cors_json_response(data, status=status)

    def audit(self, event):
        self.audit_events.append(dict(event))

    def react_sync(self, **kwargs):
        self.react_calls.append(kwargs)
        return dict(self.react_result)

    def reflect_sync(self, **kwargs):
        self.reflect_calls.append(kwargs)
        return dict(self.reflect_result)


def _make_req(method: str, path: str, body_json: Any = None, raw_body: bytes | None = None) -> web.Request:
    req = make_mocked_request(method, path, headers={"Authorization": "Bearer t"})
    if raw_body is not None:
        async def _bad_json():
            raise json.JSONDecodeError("Expecting value", "doc", 0)
        req.json = _bad_json
    else:
        async def _json():
            return body_json
        req.json = _json
    return req


# --------------------------------------------------------------------
# 0. Immutability of Handlers Container
# --------------------------------------------------------------------
def test_agentic_handlers_frozen():
    ctx = _MockContext()
    handlers = make_agentic_handlers(ctx)
    with pytest.raises(dataclasses.FrozenInstanceError):
        handlers.react = None  # type: ignore


# --------------------------------------------------------------------
# 1. handle_v1_react
# --------------------------------------------------------------------
def test_react_auth_enforced():
    ctx = _MockContext()
    handlers = make_agentic_handlers(ctx)
    req = _make_req("POST", "/v1/react", body_json={"goal": "g"})

    asyncio.run(handlers.react(req))
    assert len(ctx.auth_calls) == 1
    assert ctx.auth_calls[0] is req


def test_react_invalid_json():
    ctx = _MockContext()
    handlers = make_agentic_handlers(ctx)
    req = _make_req("POST", "/v1/react", raw_body=b"not-json")

    resp = asyncio.run(handlers.react(req))
    assert resp.status == 400
    data = json.loads(resp.text)
    assert data["ok"] is False
    assert data["error"].startswith("invalid json: ")


@pytest.mark.parametrize("bad_goal", ["", "   ", None])
def test_react_missing_goal(bad_goal):
    ctx = _MockContext()
    handlers = make_agentic_handlers(ctx)
    req = _make_req("POST", "/v1/react", body_json={"goal": bad_goal})

    resp = asyncio.run(handlers.react(req))
    assert resp.status == 400
    data = json.loads(resp.text)
    assert data == {"ok": False, "error": "missing goal"}


def test_react_happy_path_custom_params():
    ctx = _MockContext()
    handlers = make_agentic_handlers(ctx)
    payload = {
        "goal": "  Fix server memory leak  ",
        "context": "Node.js v20",
        "constraints": ["no reboot", "under 5 min"],
        "max_iterations": 8,
        "memory_profile": "custom_prof",
        "url": "https://api.example.com",
    }
    req = _make_req("POST", "/v1/react", body_json=payload)

    resp = asyncio.run(handlers.react(req))
    assert resp.status == 200
    data = json.loads(resp.text)
    assert data == ctx.react_result

    assert ctx.react_calls == [
        {
            "goal": "Fix server memory leak",
            "context": "Node.js v20",
            "constraints": ["no reboot", "under 5 min"],
            "max_iterations": 8,
            "memory_profile": "custom_prof",
            "url": "https://api.example.com",
        }
    ]

    assert ctx.audit_events == [
        {
            "event": "react_run",
            "goal": "Fix server memory leak",
            "iterations": 2,
            "profile": "browser",
        }
    ]


def test_react_happy_path_defaults():
    ctx = _MockContext()
    ctx.react_result = {"ok": True}  # iterations missing -> len 0, profile missing -> None
    handlers = make_agentic_handlers(ctx)
    req = _make_req("POST", "/v1/react", body_json={"goal": "Simple goal"})

    resp = asyncio.run(handlers.react(req))
    assert resp.status == 200

    assert ctx.react_calls == [
        {
            "goal": "Simple goal",
            "context": "",
            "constraints": [],
            "max_iterations": 4,
            "memory_profile": None,
            "url": "",
        }
    ]

    assert ctx.audit_events == [
        {
            "event": "react_run",
            "goal": "Simple goal",
            "iterations": 0,
            "profile": None,
        }
    ]


# --------------------------------------------------------------------
# 2. handle_v1_reflect
# --------------------------------------------------------------------
def test_reflect_auth_enforced():
    ctx = _MockContext()
    handlers = make_agentic_handlers(ctx)
    req = _make_req("POST", "/v1/reflect", body_json={})

    asyncio.run(handlers.reflect(req))
    assert len(ctx.auth_calls) == 1
    assert ctx.auth_calls[0] is req


def test_reflect_invalid_json():
    ctx = _MockContext()
    handlers = make_agentic_handlers(ctx)
    req = _make_req("POST", "/v1/reflect", raw_body=b"not-json")

    resp = asyncio.run(handlers.reflect(req))
    assert resp.status == 400
    data = json.loads(resp.text)
    assert data["ok"] is False
    assert data["error"].startswith("invalid json: ")


def test_reflect_happy_path_custom_params():
    ctx = _MockContext()
    handlers = make_agentic_handlers(ctx)
    payload = {
        "goal": "Build release",
        "run": {"step1": "done"},
        "notes": "all tests passed",
        "outcome": "success",
    }
    req = _make_req("POST", "/v1/reflect", body_json=payload)

    resp = asyncio.run(handlers.reflect(req))
    assert resp.status == 200
    data = json.loads(resp.text)
    assert data == ctx.reflect_result

    assert ctx.reflect_calls == [
        {
            "goal": "Build release",
            "run": {"step1": "done"},
            "notes": "all tests passed",
            "outcome": "success",
        }
    ]

    assert ctx.audit_events == [
        {
            "event": "reflect_run",
            "goal": "target goal",
            "confidence": "high",
        }
    ]


def test_reflect_happy_path_defaults():
    ctx = _MockContext()
    ctx.reflect_result = {}  # goal missing, confidence missing
    handlers = make_agentic_handlers(ctx)
    req = _make_req("POST", "/v1/reflect", body_json={})

    resp = asyncio.run(handlers.reflect(req))
    assert resp.status == 200

    assert ctx.reflect_calls == [
        {
            "goal": "",
            "run": {},
            "notes": "",
            "outcome": "",
        }
    ]

    assert ctx.audit_events == [
        {
            "event": "reflect_run",
            "goal": "",
            "confidence": "",
        }
    ]

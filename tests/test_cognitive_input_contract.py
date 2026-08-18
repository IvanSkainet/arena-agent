"""T61 strict input contracts for plan/react/reflect."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from arena.agentic.handlers import make_agentic_handlers
from arena.cognitive_input import (
    CognitiveInputError,
    optional_object,
    optional_string_list,
    optional_text,
    positive_int,
    reject_unknown,
    require_object,
    required_text,
)
from arena.planner.handlers import make_planner_handlers
from arena.public.openapi import _cognitive_request_schemas


def test_pure_field_contracts_cover_valid_defaults_and_copies() -> None:
    data = require_object({
        "goal": "  ship it  ", "context": None, "constraints": ["safe"],
        "run": {"ok": True}, "max_steps": 3,
    })
    assert required_text(data, "goal") == "ship it"
    assert optional_text(data, "context") == ""
    assert optional_text({}, "context") == ""
    constraints = optional_string_list(data, "constraints")
    assert constraints == ["safe"]
    assert constraints is not data["constraints"]
    run = optional_object(data, "run")
    assert run == {"ok": True}
    assert run is not data["run"]
    assert positive_int(data, "max_steps", 8) == 3
    assert positive_int({"max_steps": 1}, "max_steps", 8) == 1
    assert positive_int({"max_steps": None}, "max_steps", 8) == 8
    assert positive_int({}, "max_steps", 8) == 8
    reject_unknown({"goal": "x"}, frozenset({"goal"}))


@pytest.mark.parametrize("value,message", [
    ([], "JSON body must be an object"),
    (None, "JSON body must be an object"),
    ("text", "JSON body must be an object"),
])
def test_request_root_must_be_object(value: Any, message: str) -> None:
    with pytest.raises(CognitiveInputError) as caught:
        require_object(value)
    assert str(caught.value) == message


@pytest.mark.parametrize("data,message", [
    ({}, "missing goal"),
    ({"goal": None}, "missing goal"),
    ({"goal": "  "}, "missing goal"),
    ({"goal": 3}, "goal must be a string"),
    ({"goal": {}}, "goal must be a string"),
    ({"goal": []}, "goal must be a string"),
])
def test_required_goal_rejects_empty_and_coerced_values(data, message) -> None:
    with pytest.raises(CognitiveInputError) as caught:
        required_text(data, "goal")
    assert str(caught.value) == message


@pytest.mark.parametrize("call,args,message", [
    (optional_text, ({"notes": 1}, "notes"), "notes must be a string"),
    (optional_string_list, ({"constraints": "x"}, "constraints"),
     "constraints must be a list of strings"),
    (optional_string_list, ({"constraints": ["x", 1]}, "constraints"),
     "constraints must be a list of strings"),
    (optional_object, ({"run": []}, "run"), "run must be an object"),
    (positive_int, ({"max_steps": True}, "max_steps", 8),
     "max_steps must be a positive integer"),
    (positive_int, ({"max_steps": 0}, "max_steps", 8),
     "max_steps must be a positive integer"),
    (positive_int, ({"max_steps": "8"}, "max_steps", 8),
     "max_steps must be a positive integer"),
])
def test_optional_field_types_are_not_coerced(call, args, message) -> None:
    with pytest.raises(CognitiveInputError) as caught:
        call(*args)
    assert str(caught.value) == message


def test_unknown_fields_are_rejected_deterministically() -> None:
    with pytest.raises(CognitiveInputError) as caught:
        reject_unknown(
            {"goal": "x", "observations": "not-a-list", "zzz": 1},
            frozenset({"goal"}),
        )
    assert str(caught.value) == "unexpected field(s): observations, zzz"


def test_openapi_cognitive_schemas_match_strict_handler_contracts() -> None:
    plan, react, reflect = _cognitive_request_schemas()
    assert set(plan["properties"]) == {
        "goal", "context", "constraints", "memory_profile", "max_steps",
    }
    assert set(react["properties"]) == {
        "goal", "context", "constraints", "memory_profile", "max_iterations", "url",
    }
    assert set(reflect["properties"]) == {"goal", "run", "notes", "outcome"}
    for schema in (plan, react, reflect):
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["required"] == ["goal"]
        assert schema["properties"]["goal"] == {
            "type": "string", "minLength": 1, "pattern": r".*\S.*",
        }
    assert plan["properties"]["max_steps"] == {
        "type": "integer", "minimum": 1, "default": 8, "nullable": True,
    }
    assert react["properties"]["max_iterations"] == {
        "type": "integer", "minimum": 1, "default": 4, "nullable": True,
    }
    for name in ("context", "constraints", "memory_profile"):
        assert plan["properties"][name]["nullable"] is True
    for name in ("context", "constraints", "memory_profile", "url"):
        assert react["properties"][name]["nullable"] is True
    for name in ("run", "notes", "outcome"):
        assert reflect["properties"][name]["nullable"] is True


class Context:
    def __init__(self):
        self.plan_calls = []
        self.react_calls = []
        self.reflect_calls = []
        self.audit_events = []

    @staticmethod
    def require_auth(_request):
        return None

    @staticmethod
    def record_request(*_args, **_kwargs):
        return None

    @staticmethod
    def cors_json_response(data, status=200):
        return web.json_response(data, status=status)

    def audit(self, event):
        self.audit_events.append(event)

    def build_plan(self, **kwargs):
        self.plan_calls.append(kwargs)
        return {"ok": True, "steps": [], "suggested_memory_profile": None}

    def react_sync(self, **kwargs):
        self.react_calls.append(kwargs)
        return {"ok": True, "iterations": [], "memory_profile": None}

    def reflect_sync(self, **kwargs):
        self.reflect_calls.append(kwargs)
        return {"ok": True, "goal": kwargs["goal"], "confidence": "low"}


def request(path: str, body: Any):
    req = make_mocked_request("POST", path, headers={"Authorization": "Bearer t"})

    async def payload(*, loads=json.loads):
        del loads
        return body

    req.json = payload
    return req


def test_handlers_treat_explicit_null_optional_integers_as_defaults() -> None:
    ctx: Any = Context()
    planner = make_planner_handlers(ctx).plan
    agentic = make_agentic_handlers(ctx).react

    plan_response = asyncio.run(
        planner(request("/v1/plan", {"goal": "x", "max_steps": None}))
    )
    react_response = asyncio.run(
        agentic(request("/v1/react", {"goal": "x", "max_iterations": None}))
    )
    assert plan_response.status == 200
    assert react_response.status == 200
    assert ctx.plan_calls[0]["max_steps"] == 8
    assert ctx.react_calls[0]["max_iterations"] == 4


@pytest.mark.parametrize("endpoint,body,error", [
    ("plan", {"goal": {"a": 1}}, "goal must be a string"),
    ("plan", {"goal": "x", "constraints": "bad"},
     "constraints must be a list of strings"),
    ("plan", {"goal": "x", "max_steps": False},
     "max_steps must be a positive integer"),
    ("react", {"goal": 123}, "goal must be a string"),
    ("react", {"goal": "x", "max_iterations": "4"},
     "max_iterations must be a positive integer"),
    ("reflect", {}, "missing goal"),
    ("reflect", {"goal": "x", "run": []}, "run must be an object"),
    ("reflect", {"goal": "x", "observations": "bad"},
     "unexpected field(s): observations"),
])
def test_handlers_return_400_without_calling_runtime(endpoint, body, error) -> None:
    ctx: Any = Context()
    handlers = {
        "plan": make_planner_handlers(ctx).plan,
        "react": make_agentic_handlers(ctx).react,
        "reflect": make_agentic_handlers(ctx).reflect,
    }
    response = asyncio.run(handlers[endpoint](request(f"/v1/{endpoint}", body)))
    assert response.status == 400
    assert json.loads(response.text) == {"ok": False, "error": error}
    assert ctx.plan_calls == []
    assert ctx.react_calls == []
    assert ctx.reflect_calls == []

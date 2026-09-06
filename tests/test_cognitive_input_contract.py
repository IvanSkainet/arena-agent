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
from arena.handler_errors import BodyFieldError
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
])
def test_optional_field_types_are_not_coerced(call, args, message) -> None:
    with pytest.raises(CognitiveInputError) as caught:
        call(*args)
    assert str(caught.value) == message


@pytest.mark.parametrize("value,message", [
    (True, "body field 'max_steps' must be an integer, received boolean"),
    ("8", "body field 'max_steps' must be an integer, received string"),
    (0, "body field 'max_steps' must be an integer no smaller than 1, received number"),
])
def test_a_count_is_refused_as_a_named_field(value, message) -> None:
    """Still refused, and now the refusal says which field and what arrived.

    `positive_int` raised the module's own CognitiveInputError until #270,
    which meant /v1/plan and /v1/react answered 400 with a sentence and no
    `field` key -- while the document promises one for every operation with
    a numeric body field. Same three rejections, same strictness ("8" is a
    string, `True` is not 1), different envelope.
    """
    with pytest.raises(BodyFieldError) as caught:
        positive_int({"max_steps": value}, "max_steps", 8)
    assert str(caught.value) == message
    assert caught.value.field == "max_steps"


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
     "body field 'max_steps' must be an integer, received boolean"),
    ("react", {"goal": 123}, "goal must be a string"),
    ("react", {"goal": "x", "max_iterations": "4"},
     "body field 'max_iterations' must be an integer, received string"),
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
    payload = json.loads(response.text)
    # A numeric field refused since #270 also carries `field` and `received`;
    # everything this module refuses on its own carries the sentence alone.
    # Both are checked here rather than only the intersection, so that a
    # refusal quietly losing its field name is a failure.
    assert payload["ok"] is False
    assert payload["error"] == error
    named = {k: v for k, v in payload.items() if k in ("field", "received")}
    assert named == ({} if "body field" not in error
                     else {"field": error.split("'")[1],
                           "received": error.rsplit(" ", 1)[-1]})
    assert ctx.plan_calls == []
    assert ctx.react_calls == []
    assert ctx.reflect_calls == []

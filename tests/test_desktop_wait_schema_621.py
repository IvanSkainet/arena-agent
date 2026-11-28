"""#621: the one written description of a desktop wait request says what the planner does."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from arena.desktop.wait import FIELDS, plan_wait
from arena.desktop.wait_schema import wait_request_schema
from arena.handler_errors import BadRequest
from arena.mcp.tool_registry import MCP_TOOLS
from arena.public.openapi import build_openapi_spec

#: A body of each kind that the planner takes, to which one field is added or changed.
BASE = {
    "window": {"for": "window", "title": "x"},
    "screen": {"for": "screen"},
    "text": {"for": "text", "text": "x"},
}
#: What a field needs beside it to be taken at all.
BESIDE = {"stable_ms": {"until": "stable"}}
SCHEMA = wait_request_schema()
PROPERTIES = SCHEMA.get("properties", {})


def _kinds_taking(name: str) -> list[str]:
    return [kind for kind, fields in FIELDS.items() if name in fields] or list(FIELDS)


def _taken(kind: str, **fields) -> bool:
    try:
        plan_wait({**BASE[kind], **{key: value for name in fields for key, value in BESIDE.get(name, {}).items()},
                   **fields})
    except BadRequest:
        return False
    return True


def test_every_field_the_planner_takes_is_described_and_no_other():
    taken = {"for", "timeout_ms", "poll_ms"} | {name for fields in FIELDS.values() for name in fields}
    assert set(PROPERTIES) == taken
    assert all(PROPERTIES[name].get("description") for name in taken)
    assert SCHEMA["required"] == ["for"]
    assert SCHEMA["type"] == "object"


def test_the_kinds_are_the_planners_kinds():
    assert PROPERTIES["for"]["enum"] == list(FIELDS) == ["window", "screen", "text"]
    assert PROPERTIES["for"]["type"] == "string"


@pytest.mark.parametrize("name", ["timeout_ms", "poll_ms", "stable_ms", "min_confidence"])
def test_a_number_has_the_limits_the_planner_enforces(name):
    described = PROPERTIES[name]
    assert described["type"] == "integer"
    for kind in _kinds_taking(name):
        # stable_ms may not exceed the timeout, so the timeout is raised to its own limit for this.
        room = {} if name == "timeout_ms" else {"timeout_ms": PROPERTIES["timeout_ms"]["maximum"]}
        assert _taken(kind, **room, **{name: described["minimum"]})
        assert _taken(kind, **room, **{name: described["maximum"]})
        assert not _taken(kind, **room, **{name: described["minimum"] - 1})
        assert not _taken(kind, **room, **{name: described["maximum"] + 1})


@pytest.mark.parametrize(("name", "kind", "where"), [
    ("timeout_ms", "window", lambda plan: plan.timeout_ms),
    ("poll_ms", "window", lambda plan: plan.poll_ms),
    ("stable_ms", "screen", lambda plan: plan.want["stable_ms"]),
    ("min_confidence", "text", lambda plan: plan.want["min_confidence"]),
    ("state", "window", lambda plan: plan.want["state"]),
    ("state", "text", lambda plan: plan.want["state"]),
    ("until", "screen", lambda plan: plan.want["until"]),
])
def test_a_default_is_what_the_planner_uses_when_the_field_is_left_out(name, kind, where):
    body = {key: value for key, value in {**BASE[kind], **BESIDE.get(name, {})}.items() if key != name}
    assert where(plan_wait(body)) == PROPERTIES[name]["default"]


@pytest.mark.parametrize("name", ["state", "until"])
def test_a_choice_lists_the_values_some_kind_of_wait_takes_and_only_those(name):
    described = PROPERTIES[name]
    assert described["type"] == "string"
    for value in described["enum"]:
        assert any(_taken(kind, **{name: value}) for kind in _kinds_taking(name)), value
    assert not any(_taken(kind, **{name: "something-else"}) for kind in _kinds_taking(name))


@pytest.mark.parametrize("name", ["title", "class", "text"])
def test_words_are_strings(name):
    assert PROPERTIES[name]["type"] == "string"
    for kind in _kinds_taking(name):
        assert _taken(kind, **{name: "words"})
        assert not _taken(kind, **{name: 7})


def test_a_region_is_four_whole_numbers_and_nothing_else():
    region = PROPERTIES["region"]
    assert region["type"] == "object"
    assert region["required"] == ["x", "y", "width", "height"]
    assert region["properties"] == {name: {"type": "integer"} for name in region["required"]}
    whole = dict.fromkeys(region["required"], 5)
    for kind in _kinds_taking("region"):
        assert _taken(kind, region=whole)
        assert not _taken(kind, region={**whole, "depth": 1})
        for name in region["required"]:
            assert not _taken(kind, region={key: value for key, value in whole.items() if key != name})
            assert not _taken(kind, region={**whole, name: 5.5})
            assert not _taken(kind, region={**whole, name: "five"})


def test_what_is_not_described_is_refused_by_the_schema_as_it_is_by_the_planner():
    assert SCHEMA["additionalProperties"] is False
    assert PROPERTIES["region"]["additionalProperties"] is False
    assert not any(_taken(kind, anything_else=1) for kind in FIELDS)


def test_each_caller_gets_a_description_of_its_own():
    first = wait_request_schema()
    first["properties"]["region"]["properties"].clear()
    first["properties"]["for"]["enum"].append("mouse")
    del first["properties"]["title"]
    assert wait_request_schema() == SCHEMA


def test_the_route_and_the_tool_both_use_it():
    ctx = SimpleNamespace(version="test", hostname=lambda: "h", bridge_port=lambda: 8765)
    route = build_openapi_spec(ctx)["paths"]["/v1/desktop/wait"]["post"]["requestBody"]["content"]
    assert route["application/json"]["schema"] == SCHEMA
    tool = next(tool for tool in MCP_TOOLS if tool["name"] == "desktop.wait")
    assert tool["inputSchema"] == SCHEMA


def test_the_wording_changes_only_on_purpose():
    """The descriptions are read by a model deciding what to send. After a deliberate change, record the new digest."""
    written = json.dumps(SCHEMA, sort_keys=True, ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(written).hexdigest() == "c64a9f5d8e0d8ee7aa6a670bfbbecd05ac94e67982e4416b187b6ffae809e27e"

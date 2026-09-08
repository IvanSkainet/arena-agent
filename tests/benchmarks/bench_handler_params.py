"""Benchmarks for request parsing and shape coercion.

Three layers run on every HTTP request the bridge answers, before any
handler logic does:

* ``arena.jsonshape`` -- ``json.loads`` with the declared shape enforced,
  used wherever a document could legally be ``null``, ``5`` or ``[1]``;
* ``arena.safe_numeric`` -- bounded, finite parsing of caller-supplied
  numbers, on the reject path as well as the accept path;
* ``arena.handler_params`` -- the typed body readers that turn a bad field
  into a 400 instead of a 500.

The refusal paths are benchmarked alongside the happy paths on purpose:
they raise, and an exception is not free. A client sending malformed
input repeatedly must not be cheaper to serve for the client than for us.
"""
from __future__ import annotations

import json

from arena.handler_params import (
    BodyFieldError,
    body_float,
    body_int,
    body_str,
    body_str_list,
    is_string_list,
)
from arena.jsonshape import as_object, loads_array, loads_object
from arena.safe_numeric import safe_float, safe_int

# A mission descriptor of the size the bridge actually moves around:
# nested objects, a list of steps, mixed value types.
MISSION_JSON = json.dumps({
    "id": "m-4711",
    "title": "Rebuild the dashboard bundle and publish the report",
    "created_at": "2026-01-01T00:00:00+00:00",
    "labels": ["build", "dashboard", "nightly"],
    "limits": {"timeout_s": 900, "max_retries": 3, "memory_mb": 2048},
    "steps": [
        {"op": "exec", "cmd": "npm ci", "cwd": "dashboard", "timeout_s": 300},
        {"op": "exec", "cmd": "npm run build", "cwd": "dashboard", "timeout_s": 600},
        {"op": "file.read", "path": "dashboard/dist/report.json"},
        {"op": "http", "method": "POST", "url": "https://example.com/ingest"},
    ],
    "meta": {"agent": "arena-agent/4.170.0", "dry_run": False, "priority": 5},
})
STEPS_JSON = json.dumps([
    {"op": "exec", "cmd": f"echo step-{index}", "timeout_s": 30}
    for index in range(24)
])
# Valid JSON of the wrong shape: the case the module exists for.
NULL_JSON = "null"

REQUEST_BODY: dict[str, object] = {
    "mission_id": "m-4711",
    "timeout_s": 900,
    "max_retries": "3",
    "priority": 5.0,
    "threshold": 0.75,
    "labels": ["build", "dashboard", "nightly"],
    "dry_run": False,
}
# Every field is a shape the readers must refuse rather than coerce.
BAD_BODY: dict[str, object] = {
    "timeout_s": [],
    "max_retries": True,
    "priority": "not-a-number",
    "threshold": {},
    "labels": ["ok", 7],
}
NUMERIC_INPUTS = ["1.5", " 42 ", "0", "-7", "1e3", "nan", "inf", "abc", "", "10" * 40]


def test_loads_object_mission(benchmark) -> None:
    """Shape-checked parse of a realistic mission document."""
    parsed = benchmark(loads_object, MISSION_JSON)
    assert parsed["id"] == "m-4711"


def test_loads_array_steps(benchmark) -> None:
    """Shape-checked parse of a 24-element step list."""
    assert len(benchmark(loads_array, STEPS_JSON)) == 24


def test_loads_object_wrong_shape(benchmark) -> None:
    """``null`` is valid JSON and not a mapping -- the substitution path."""
    assert benchmark(loads_object, NULL_JSON) == {}


def test_as_object_already_parsed(benchmark) -> None:
    """Coercion without a re-parse, the cheapest of the three."""
    value = {"a": 1, "b": 2}
    assert benchmark(as_object, value) is value


def test_safe_numeric_mixed_inputs(benchmark) -> None:
    """Accepted and refused numbers together, with clamping in play."""

    def parse_all() -> int:
        total = 0
        for raw in NUMERIC_INPUTS:
            total += int(safe_float(raw, default=0.0, minimum=-1000.0, maximum=1000.0))
            total += safe_int(raw, default=0, minimum=-1000, maximum=1000)
        return total

    benchmark(parse_all)


def test_body_readers_valid_request(benchmark) -> None:
    """The typed readers over a well-formed body."""

    def read_all() -> tuple[object, ...]:
        return (
            body_str(REQUEST_BODY, "mission_id", default=""),
            body_int(REQUEST_BODY, "timeout_s", default=60, bounds=(1, 86_400)),
            body_int(REQUEST_BODY, "max_retries", default=0, bounds=(0, 10)),
            body_int(REQUEST_BODY, "priority", default=0),
            body_float(REQUEST_BODY, "threshold", default=0.5),
            body_str_list(REQUEST_BODY, "labels", default=[]),
        )

    assert benchmark(read_all)[1] == 900


def test_body_readers_refusal_path(benchmark) -> None:
    """Six refusals, so the cost of raising is measured, not assumed."""

    def refuse_all() -> int:
        refused = 0
        for name, read in (
            ("timeout_s", lambda: body_int(BAD_BODY, "timeout_s", default=60)),
            ("max_retries", lambda: body_int(BAD_BODY, "max_retries", default=0)),
            ("priority", lambda: body_int(BAD_BODY, "priority", default=0)),
            ("threshold", lambda: body_float(BAD_BODY, "threshold", default=0.5)),
            ("labels", lambda: body_str_list(BAD_BODY, "labels", default=[])),
        ):
            try:
                read()
            except BodyFieldError:
                refused += 1
            assert name
        return refused

    assert benchmark(refuse_all) == 5


def test_is_string_list(benchmark) -> None:
    """The list-shape predicate used by every list-valued field."""
    cases = [["a", "b"], [], ["a", 1], "not-a-list", None, ["x"] * 32]

    def check_all() -> int:
        return sum(1 for case in cases if is_string_list(case))

    assert benchmark(check_all) == 3

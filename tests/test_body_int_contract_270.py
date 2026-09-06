"""A malformed number in a JSON body is the caller's mistake, not a 500 (#270).

#254 settled this for query strings. Schemathesis, run against the #260
branch, found the same defect one layer over -- thirteen (operation, field)
pairs where a body a client can send by accident produced::

    POST /v1/desktop/focus  {"pid": {}}
      -> 500 {"ok": false,
              "error": "TypeError: int() argument must be a string, a
                        bytes-like object or a real number, not 'dict'",
              "error_type": "TypeError"}

Two defects again, the same two: the status blames the bridge for a request
it was right to refuse, so retry logic waits and the `/v1/status` error
counter climbs; and the envelope names a Python builtin, which #254 and #259
both spent tests pinning as absent everywhere else.

The sweep is the part that matters -- `body_int` at thirteen call sites is
worth little if the fourteenth handler reaches for `int(body.get(...))`
again. Two things guard that here: the live sweep below, driven off the
document through the real aiohttp stack, and `test_no_new_int_over_a_request
_body_appears` further down, which reads the source and holds the remaining
call sites to a list that may shrink and may not grow.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient

from arena.handler_helpers import BodyFieldError, body_int
from arena.handler_params import body_str
from arena.public.openapi import build_openapi_spec
from tests._live_bridge import (
    auth_header,
    error_type_of,
    json_payload,
    running_client,
)

TOKEN = "body-int-contract-token"

# What a client sends by accident, and what a fuzzer sends on purpose. Every
# one is legal JSON -- the request is well formed, the value is not a number.
#
# `[]` and `{}` are here deliberately even though they are falsy: the idiom
# being replaced, `int(body.get("psm", 11) or 11)`, accepted both by turning
# them into the default, which is how a caller sending `{"psm": []}` learned
# nothing about their mistake. The empty containers are the ones the old code
# swallowed; the non-empty ones are the ones it crashed on.
BAD_NUMBERS = ([1, 2], [], {"a": 1}, {}, "abc", "null", "", True, False, 1.5, "1e999")

# Values that must keep working, because they work today.
GOOD_NUMBERS = (7, "7", 2.0, 0, -1)


@pytest.fixture(scope="module")
def spec() -> dict:
    return build_openapi_spec(
        SimpleNamespace(version="test", hostname=lambda: "h", bridge_port=lambda: 8765)
    )


def _json_body_schema(operation: object) -> dict:
    """The object schema this operation reads, or `{}` for the ones that do not."""
    if not isinstance(operation, dict):
        return {}
    return (operation.get("requestBody", {}).get("content", {})
            .get("application/json", {}).get("schema", {}))


def _concrete_body_operations(spec: dict) -> Iterator[tuple[str, str, dict]]:
    """Every non-templated operation that reads a JSON object body."""
    for path, item in spec["paths"].items():
        if "{" in path:
            continue  # needs an id that exists on the machine running this
        for method, operation in item.items():
            if _json_body_schema(operation).get("properties"):
                yield method, path, operation


def _numeric_body_fields(spec: dict) -> list[tuple[str, str, str, dict]]:
    """(method, path, field, schema) for every numeric field in the document."""
    found = []
    for method, path, operation in _concrete_body_operations(spec):
        schema = (operation["requestBody"]["content"]["application/json"]["schema"])
        for field, declared in (schema.get("properties") or {}).items():
            if declared.get("type") in ("integer", "number"):
                found.append((method, path, field, schema))
    return found


def _filler(schema: dict, skip: str) -> dict:
    """The required fields of an operation, so the sweep reaches the parse.

    Without them a handler answers "missing 'query'" before it ever looks at
    the field under test, and the sweep passes by never arriving.
    """
    types = {"string": "x", "integer": 1, "number": 1, "boolean": True,
             "array": [], "object": {}}
    return {
        name: types.get((schema.get("properties", {}).get(name) or {}).get("type"), "x")
        for name in schema.get("required", []) or []
        if name != skip
    }


# --- the helper in isolation -------------------------------------------

def test_body_int_reads_the_values_that_work_today():
    assert body_int({"n": 7}, "n", default=1) == 7
    assert body_int({"n": "7"}, "n", default=1) == 7
    assert body_int({"n": " 7"}, "n", default=1) == 7


def test_missing_null_and_empty_all_mean_unspecified():
    """The `int(body.get("psm", 11) or 11)` idiom accepted all three.

    Losing any of them would turn a working request into a 400 -- a
    regression riding along inside a bug fix, which is what #254 warned
    about when the same helper landed for query strings.
    """
    for body in ({}, {"n": None}, {"n": ""}):
        assert body_int(body, "n", default=11) == 11


def test_a_whole_float_is_the_same_number_and_a_fractional_one_is_not():
    """`2.0` is accepted, `2.5` is refused, and neither is silently truncated.

    Languages without an integer type send `2.0` for two, so refusing it
    would break real callers. `int(2.5)` is 2, which is a different number
    from the one the caller sent -- the kind of quiet coercion #254 called
    out when it removed `safe_int(raw, default=50)` from the query path.
    """
    assert body_int({"n": 2.0}, "n", default=1) == 2
    with pytest.raises(BodyFieldError):
        body_int({"n": 2.5}, "n", default=1)


def test_a_boolean_is_not_a_number_even_though_python_says_it_is():
    """`int(True)` is 1, so `bool` has to be refused before the isinstance.

    Without the explicit check `{"max_results": true}` would quietly mean
    one result, and `bool` being a subclass of `int` makes that the default
    behaviour rather than an exotic case.
    """
    for value in (True, False):
        with pytest.raises(BodyFieldError) as caught:
            body_int({"n": value}, "n", default=1)
        assert caught.value.received == "boolean"


@pytest.mark.parametrize("bad,expected", [
    ([1, 2], "array"), ({"a": 1}, "object"), ("abc", "string"), (1.5, "number"),
])
def test_the_refusal_names_the_field_and_the_json_type(bad, expected):
    with pytest.raises(BodyFieldError) as caught:
        body_int({"psm": bad}, "psm", default=11)
    assert caught.value.field == "psm"
    assert caught.value.received == expected
    assert "psm" in str(caught.value)


def test_the_refusal_never_echoes_the_value():
    """#259's rule: the type is a fixed word, the value is attacker text."""
    error = BodyFieldError("psm", "<script>alert(1)</script>")
    assert "<script>" not in str(error)
    assert dict(error.details) == {"field": "psm", "received": "string"}


def test_a_number_that_reaches_a_system_call_has_a_bound():
    """`{"timeout": 1578655390615}` was a 500, and the number was valid JSON.

    It ends up in `subprocess.run(timeout=...)`, where selectors.poll
    answers `OverflowError: timestamp too large to convert to C PyTime_t`.
    `query_int` deliberately has no bounds because every caller passed its
    value to a layer that clamped it; a body number can reach the system
    call directly, so the handlers that do say what they accept. The
    negative side is the same defect with the sign flipped.
    """
    assert body_int({"t": 300}, "t", default=180, bounds=(1, 86_400)) == 300
    for bad, word in ((1578655390615, "greater"), (-174294, "smaller")):
        with pytest.raises(BodyFieldError) as caught:
            body_int({"t": bad}, "t", default=180, bounds=(1, 86_400))
        assert word in str(caught.value), str(caught.value)
        assert caught.value.field == "t"


def test_a_string_field_is_a_string_and_not_whatever_str_accepts():
    """`{"cwd": {...}}` became a path made of a dict's repr.

    `str()` never refuses, so the object turned into a 400-character
    directory name and `Path.exists()` answered `OSError: [Errno 36] File
    name too long`. The fuzzing gate found it; `body_str` is `body_int`'s
    counterpart, and refuses numbers too -- "12" as a directory is a typo
    that should be visible, not a directory called 12.
    """
    # Bare directory names, not "/tmp/...": the helper never touches the
    # filesystem, and a literal temp path here reads to bandit (B108) as
    # code that does.
    assert body_str({"cwd": "workspace"}, "cwd", default="") == "workspace"
    assert body_str({}, "cwd", default="fallback") == "fallback"
    for bad, received in (({"a": 1}, "object"), ([1], "array"), (12, "number"), (True, "boolean")):
        with pytest.raises(BodyFieldError) as caught:
            body_str({"cwd": bad}, "cwd", default="")
        assert caught.value.received == received
        assert "a string" in str(caught.value)


def test_body_field_error_is_a_valueerror():
    """Handlers that already wrote `except ValueError: use_default` keep it."""
    assert issubclass(BodyFieldError, ValueError)


# --- the behaviour, through the real server ----------------------------

def _auth() -> dict[str, str]:
    return auth_header(TOKEN)


@asynccontextmanager
async def _running_client(root: Path) -> AsyncIterator[TestClient]:
    async with running_client(root, TOKEN) as client:
        yield client


def test_no_documented_endpoint_answers_5xx_to_a_bad_body_number(spec, tmp_path):
    """The property #270 asks for, over every numeric body field documented."""
    asyncio.run(_sweep(spec, tmp_path))


async def _sweep(spec, root):
    targets = _numeric_body_fields(spec)
    assert targets, "the document declares no numeric body fields -- sweep is vacuous"

    crashed, leaked = [], []
    async with _running_client(root) as client:
        for method, path, field, schema in targets:
            for bad in BAD_NUMBERS:
                body = _filler(schema, field)
                body[field] = bad
                response = await getattr(client, method)(
                    path, json=body, headers=_auth())
                payload = await json_payload(response)
                where = f"{method.upper()} {path} {field}={bad!r}"
                if response.status >= 500:
                    if payload.get("unavailable"):
                        continue  # the box has no tool for this (#260)
                    crashed.append(f"{where} -> {response.status} {payload}")
                elif error_type_of(payload) is not None:
                    leaked.append(f"{where} -> {error_type_of(payload)}")

    assert crashed == [], (
        "a malformed body number must not be reported as a server fault: "
        + "; ".join(crashed))
    assert leaked == [], (
        "the error envelope must not name the Python exception class: "
        + "; ".join(leaked))


def test_the_three_endpoints_the_issue_named_answer_400_and_say_which_field(tmp_path):
    """The measurements in #270, turned into assertions.

    The sweep above proves no 5xx; these three prove the refusal is *useful*.
    A 400 that says only "bad request" would pass the sweep and leave the
    caller exactly as stuck as the 500 did.
    """
    asyncio.run(_check_named_fields(tmp_path))


async def _check_named_fields(root):
    cases = [
        ("/v1/desktop/focus", {"pid": {}}, "pid", "object"),
        ("/v1/desktop/resolve_text_target",
         {"query": "x", "max_results": [None, None]}, "max_results", "array"),
        ("/v1/desktop/text_action",
         {"query": "x", "timeout_ms": [None, None]}, "timeout_ms", "array"),
    ]
    async with _running_client(root) as client:
        for path, body, field, received in cases:
            response = await client.post(path, json=body, headers=_auth())
            payload = await json_payload(response)
            assert response.status == 400, f"{path} -> {response.status} {payload}"
            assert payload["field"] == field, payload
            assert payload["received"] == received, payload
            assert error_type_of(payload) is None, payload


def test_what_the_fuzzer_found_answers_400_now(tmp_path):
    """The five shapes the first gated Schemathesis run turned up.

    Each was a 500 on a request that is valid JSON, and each is a different
    corner: an out-of-range number, a negative one, an object where a string
    belongs, and -- twice -- a read of data an earlier write had accepted.
    """
    asyncio.run(_check_fuzzer_findings(tmp_path))


async def _check_fuzzer_findings(root):
    async with _running_client(root) as client:
        for path, body, field in (
            ("/v1/mission/run", {"mission_id": "x", "timeout": 1578655390615}, "timeout"),
            ("/v1/mission/run", {"mission_id": "x", "timeout": -174294}, "timeout"),
            ("/v1/mission/compose", {"goal": "x", "max_steps": [None, None]}, "max_steps"),
            ("/v1/exec", {"cmd": "echo hi", "cwd": {"a": 1}}, "cwd"),
        ):
            response = await client.post(path, json=body, headers=_auth())
            payload = await json_payload(response)
            assert response.status == 400, f"{path} {body} -> {response.status} {payload}"
            assert payload["field"] == field, payload
            assert error_type_of(payload) is None, payload


def test_a_digest_survives_whatever_the_api_let_someone_store(tmp_path):
    """A write the API accepted must not break every later read.

    `{"tags": [null]}` stored fine and then `", ".join` raised TypeError on
    the way out, so `/v1/recall/digest` answered 500 for as long as the fact
    existed -- one poisoned row, endpoint down. Same for an audit line whose
    `cmd` is a number.
    """
    from arena.memory.recall import recall_digest

    result = recall_digest(
        facts=[{"key": "k", "value": "v", "tags": [None, 12]},
               {"key": "k2", "tags": "not-a-list"},
               "not-a-dict-at-all"],
        audit_lines=['{"type": "exec", "cmd": 12}', '{"type": "read", "path": 7}', "3"],
        utc_now_fn=lambda: "2026-01-01T00:00:00Z")
    assert result["ok"] is True
    assert "None, 12" in result["digest"]


def test_a_good_value_still_gets_through(tmp_path):
    """The fix must not turn working requests into refusals.

    `/v1/exec` is the one endpoint in the sweep that both takes an integer
    and runs without a desktop, so it is where "still works" can actually be
    observed rather than inferred from the absence of a 400.
    """
    asyncio.run(_check_good_values(tmp_path))


async def _check_good_values(root):
    async with _running_client(root) as client:
        for good in GOOD_NUMBERS:
            if isinstance(good, int) and good <= 0:
                continue  # a zero or negative timeout is a different question
            response = await client.post(
                "/v1/exec", json={"cmd": "echo hi", "timeout": good},
                headers=_auth())
            payload = await json_payload(response)
            assert response.status == 200, f"timeout={good!r} -> {payload}"


# --- the class, not just the thirteen ----------------------------------

# Call sites that still read a number straight out of a request-like dict.
# Every one of these is either unreachable over HTTP with a bad value or
# guarded by its own try/except; the sweep above and a Schemathesis run over
# the whole document confirm none of them answers 5xx today. The list exists
# so that a *new* one cannot appear unnoticed -- it may shrink, never grow,
# and four entries left it when the fuzzing gate reached the mission
# endpoints through their executor.
KNOWN_RAW_NUMBER_READS = {
    "arena/api_v2/exec_handler.py",
    "arena/cluster/handlers.py",
    "arena/extension_bridge/runtime.py",
    "arena/gateway/handlers.py",
    "arena/grpc/handlers.py",
    "arena/input_helper/helper_server.py",
    "arena/mobile/handlers_devops.py",
    "arena/mobile/handlers_media.py",
    "arena/mobile/handlers_recording.py",
    "arena/observability/tracing_config_handler.py",
    "arena/rate_limit.py",
    "arena/sandbox/handlers.py",
    "arena/system/handlers.py",
    "arena/watchdog/handlers.py",
}

_BODY_NAMES = ("body", "data", "payload")
_READ = re.compile(r"^(body|data|payload)(?:\.get\(|\[)['\"]")


def _files_reading_numbers_from_a_body() -> set[str]:
    """Source files calling int()/float() straight on a body field.

    An AST walk rather than a grep: `int(body.get("x", 1) or 1)` and
    `int(body["x"])` are the same defect written two ways, and a grep tight
    enough to catch both catches comments and docstrings as well.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    found = set()
    for source in (root / "arena").rglob("*.py"):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - the repo does not have any
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("int", "float") and node.args
                    and _READ.match(ast.unparse(node.args[0]))):
                found.add(str(source.relative_to(root)).replace("\\", "/"))
    return found


def test_no_new_int_over_a_request_body_appears():
    """A ratchet, because thirteen fixed call sites do not close a class.

    The files listed above predate #270 and none of them is reachable with a
    bad value today -- proven by the wide sweep run while writing this, over
    all 87 non-destructive POST routes in the registry rather than only the
    67 documented ones. What this test stops is the *next* handler: written
    with `int(body.get("limit", 50))`, shipped, and then found by a fuzzer
    for the third time.
    """
    current = _files_reading_numbers_from_a_body()
    # System files read WMI output, not request bodies; the name collision is
    # `data`, and rewriting them would be a change with no defect behind it.
    current -= {"arena/system/hwinfo_windows.py", "arena/system/sysinfo.py"}
    new = sorted(current - KNOWN_RAW_NUMBER_READS)
    assert new == [], (
        "these files read a number straight out of a request body -- use "
        f"body_int (#270): {new}")
    gone = sorted(KNOWN_RAW_NUMBER_READS - current)
    assert gone == [], (
        "cleaned up, so remove them from KNOWN_RAW_NUMBER_READS to keep the "
        f"ratchet tight: {gone}")

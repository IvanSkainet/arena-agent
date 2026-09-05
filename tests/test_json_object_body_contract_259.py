"""A body of the wrong shape is the caller's mistake, not the server's (#259).

Found by pointing Schemathesis at a live bridge on the commit that closed
#254. Measured there, with a valid token::

    POST /v1/desktop/focus  -d 'false'
      -> 500 {"ok": false,
              "error": "AttributeError: 'bool' object has no attribute 'get'",
              "error_type": "AttributeError"}

Twenty-four of the thirty-three documented write operations did that, in
three flavours: an `AttributeError` from `data.get`, a `TypeError` from
`**data`, and a bare `Internal server error` envelope. Every one of
`false`, `[]`, `"x"`, `null` and `1` triggered it -- all valid JSON, all
legal HTTP, only the shape wrong.

The same two defects as #254 in one response. The status blames the server,
so retry logic waits and the `/v1/status` counter climbs for something the
bridge did nothing wrong in; and the body names a Python exception class,
which is implementation detail crossing the API boundary.

Third time for this shape. `parse_json_body` already made the isinstance
check and had done for many releases; the handlers had each hand-written a
`try/except` around `await request.json()` that caught a *parse* failure and
then handed the bool straight to `.get`. So the sweep, not the twenty-four
fixes, is the part of this module that matters: the property is that no
documented operation with a JSON body answers 5xx to one, driven through the
real aiohttp stack.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import unified_bridge as ub
from arena.handler_helpers import (
    BadRequest,
    JsonBodyError,
    json_object_body,
)
from arena.public.openapi import build_openapi_spec

TOKEN = "json-body-contract-token"

# The five bodies measured against the live bridge. Each is valid JSON and a
# well-formed request; only the top-level shape is not an object.
#
# `null` is in the list on purpose. It is the one value a "did the parse
# work?" check cannot distinguish from failure if the helper uses None as a
# sentinel -- which is why the helper uses a private object() instead.
BAD_BODIES: tuple[tuple[str, str], ...] = (
    ("false", "boolean"),
    ("[]", "array"),
    ('"x"', "string"),
    ("null", "null"),
    ("1", "number"),
)


@pytest.fixture(scope="module")
def spec() -> dict:
    return build_openapi_spec(
        SimpleNamespace(version="test", hostname=lambda: "h", bridge_port=lambda: 8765)
    )


_WRITE_METHODS = ("post", "put", "patch", "delete")


def _json_body_operations(spec: dict) -> Iterator[tuple[str, str, dict]]:
    """Every documented operation whose handler reads a JSON object body.

    Templated paths are skipped: they need an id that exists on the machine
    running the test, which is a different problem from reading a body.

    The media type is checked rather than the mere presence of a body:
    `POST /v1/exec/script` takes `text/plain`, where a bare `false` is a
    perfectly good script and must not be refused.
    """
    for path, item in spec["paths"].items():
        if "{" in path:
            continue
        for method, operation in item.items():
            if method not in _WRITE_METHODS:
                continue
            content = operation.get("requestBody", {}).get("content", {})
            if "application/json" in content:
                yield path, method, operation


# --- the helper in isolation -------------------------------------------

class _FakeRequest:
    """Enough of aiohttp's request for the helper: a body and a flag."""

    def __init__(self, payload=None, *, raises=False, can_read_body=True) -> None:
        self._payload = payload
        self._raises = raises
        self.can_read_body = can_read_body

    async def json(self):
        if self._raises:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


def _run(coro):
    return asyncio.run(coro)


def test_an_object_body_is_returned_unchanged():
    assert _run(json_object_body(_FakeRequest({"a": 1}))) == {"a": 1}


@pytest.mark.parametrize("payload,name", [
    (False, "boolean"), (True, "boolean"), ([], "array"), ([1], "array"),
    ("x", "string"), (None, "null"), (1, "number"), (1.5, "number"),
])
def test_every_non_object_json_type_is_refused_by_name(payload, name):
    with pytest.raises(JsonBodyError) as caught:
        _run(json_object_body(_FakeRequest(payload)))
    assert caught.value.received == name
    assert caught.value.details == {"received": name}


def test_a_body_that_is_not_json_at_all_is_refused_without_a_type():
    """Nothing parsed, so there is no JSON type to name -- and none is invented.

    `received` stays absent from the envelope rather than arriving as a
    guess: a client branching on it would otherwise be told the body was a
    `null` when it was actually truncated bytes.
    """
    with pytest.raises(JsonBodyError) as caught:
        _run(json_object_body(_FakeRequest(raises=True)))
    assert caught.value.received is None
    assert caught.value.details == {}
    assert "valid JSON" in str(caught.value)


class _NotAJsonType:
    """What a custom `json.loads` decoder could hand back. Nothing else can."""


def test_a_value_outside_the_five_types_is_refused_without_inventing_one():
    """The unreachable branch, pinned rather than trusted.

    `json.loads` cannot produce this, so the only way to know the fallback
    answers 400 instead of raising KeyError -- a 500 from inside the error
    path -- is to call it.
    """
    with pytest.raises(JsonBodyError) as caught:
        _run(json_object_body(_FakeRequest(_NotAJsonType())))
    assert caught.value.received is None
    assert caught.value.details == {}
    assert str(caught.value) == "request body must be a JSON object"


def test_the_message_names_the_type_and_never_the_value():
    """`received` is one of six fixed words, so nothing reflects back out.

    An error that echoed the body would put attacker-controlled text into
    logs and dashboards. The type name cannot: it comes from a lookup table,
    not from the request.
    """
    error = JsonBodyError("<script>alert(1)</script>")
    assert "script" not in str(error)
    assert error.received == "string"


def test_an_empty_body_is_only_an_object_when_the_handler_says_so():
    """`allow_empty` is opt-in, because an empty body is not an object either.

    `POST /v1/desktop/ocr` has no required field, so a body-less request is a
    real one. Making that the default would let a handler with required
    fields see `{}` and fall over further in, which is the bug this module
    is about, one layer down.
    """
    empty = _FakeRequest(can_read_body=False)
    assert _run(json_object_body(empty, allow_empty=True)) == {}
    with pytest.raises(JsonBodyError):
        _run(json_object_body(_FakeRequest(can_read_body=False, raises=True)))


def test_allow_empty_does_not_excuse_a_body_of_the_wrong_shape():
    """The concession is for *no* body. A body that arrived is still checked."""
    with pytest.raises(JsonBodyError) as caught:
        _run(json_object_body(_FakeRequest(False, can_read_body=True), allow_empty=True))
    assert caught.value.received == "boolean"


def test_json_body_error_is_a_bad_request_and_a_valueerror():
    """Both parents earn their place.

    `BadRequest` is what the handler decorators catch, so raising is enough
    to produce the 400. `ValueError` keeps any handler that already wrote
    `except ValueError` behaving as it does today when it adopts the helper
    -- the same reason `QueryParamError` is one (#254).
    """
    assert issubclass(JsonBodyError, BadRequest)
    assert issubclass(JsonBodyError, ValueError)


# --- the behaviour, through the real server ----------------------------

def _build_app(root: Path) -> web.Application:
    app = ub.make_app({
        "token": TOKEN, "profile": "owner-shell", "root": root,
        "active_exec": 0, "max_concurrent": 3, "audit": "audit",
        "timeout": 60, "max_timeout": 3600, "max_output": 2000000,
        "allow_any_cwd": False, "semaphore": asyncio.Semaphore(1),
    })
    # Lifecycle hooks tear down the shared executor and poison later tests;
    # routing and parsing do not need the background workers.
    app.on_startup.clear()
    app.on_cleanup.clear()
    app.on_shutdown.clear()
    return app


@asynccontextmanager
async def _running_client(root: Path) -> AsyncIterator[TestClient]:
    log = logging.getLogger("arena-bridge")
    previous = log.level
    log.setLevel(logging.CRITICAL)  # a regression here logs a traceback
    server = TestServer(_build_app(root))
    await server.start_server()
    client = TestClient(server)
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()
        await server.close()
        log.setLevel(previous)
        store = getattr(ub, "_rate_limit_store", None)
        if isinstance(store, dict):
            store.clear()


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


async def _payload(response) -> dict:
    if response.content_type != "application/json":
        return {}
    try:
        body = json.loads(await response.text())
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _error_type_of(payload: dict) -> str | None:
    return payload.get("error_type")


def test_the_leak_detector_would_actually_notice_a_leak():
    """A detector nothing currently trips is a detector nobody has tested.

    Since the fix no documented operation returns `error_type`, so the
    sweep's leak arm never fires on green code. Pin it directly, or the arm
    could be broken and the sweep would go on passing.
    """
    assert _error_type_of({"ok": False, "error_type": "AttributeError"}) == "AttributeError"
    assert _error_type_of({"ok": False, "error": "request body must be"}) is None
    assert _error_type_of({}) is None


def test_no_documented_json_endpoint_answers_5xx_to_a_body_of_the_wrong_shape(
        spec, tmp_path):
    """The property #259 asks for, over every documented JSON body.

    asyncio.run rather than a pytest-asyncio marker: this repo does not
    depend on the plugin, and --strict-markers turns an unknown marker into
    a collection error.

    No environment excuse here, unlike the #254 sweep. A body-shape refusal
    is raised while the handler is still reading the request, before it
    touches anything the box might not have -- so even the OCR endpoints,
    which cannot work without tesseract installed, owe a 400.
    """
    asyncio.run(_sweep(spec, tmp_path))


async def _sweep(spec, root):
    targets = list(_json_body_operations(spec))
    assert targets, "the document declares no JSON request bodies -- sweep is vacuous"

    wrong: list[str] = []
    async with _running_client(root) as client:
        for path, method, _operation in targets:
            for body, expected_type in BAD_BODIES:
                response = await client.request(
                    method.upper(), path, data=body, headers=_auth())
                payload = await _payload(response)
                where = f"{method.upper()} {path} -d {body}"
                # The status alone is not the whole contract. A 400 that
                # says "missing cmd" would pass a status-only check while
                # telling the caller to fix the wrong thing.
                if response.status != 400:
                    wrong.append(f"{where} -> {response.status} {payload or '(no json)'}")
                elif payload.get("received") != expected_type:
                    wrong.append(f"{where} -> 400 but received={payload.get('received')!r}")
                elif _error_type_of(payload) is not None:
                    wrong.append(f"{where} -> leaks error_type={_error_type_of(payload)}")
                elif payload.get("ok") is not False:
                    wrong.append(f"{where} -> 400 without ok:false: {payload}")

    assert wrong == [], (
        "a JSON body of the wrong shape must be refused with a 400 that names "
        "the type received: " + "; ".join(wrong)
    )


def test_the_endpoint_the_issue_was_filed_about_gives_the_useful_answer(tmp_path):
    """Not just "no 5xx" -- the replacement has to tell the caller something.

    A handler that swallowed the bad body and answered 200 would also pass
    the sweep while leaving the client none the wiser.
    """
    asyncio.run(_check_the_measured_endpoint(tmp_path))


async def _check_the_measured_endpoint(root):
    async with _running_client(root) as client:
        response = await client.post(
            "/v1/desktop/focus", data="false", headers=_auth())
        payload = await response.json()
        assert response.status == 400, payload
        assert payload == {
            "ok": False,
            "error": "request body must be a JSON object, received boolean",
            "received": "boolean",
        }, payload


def test_a_valid_body_still_works(tmp_path):
    """The refusal path is worthless if it also refuses good input.

    `/v1/memory` is the check: it takes an object, needs no hardware, and
    both of its methods were among the twenty-four.
    """
    asyncio.run(_check_happy_path(tmp_path))


async def _check_happy_path(root):
    async with _running_client(root) as client:
        written = await client.post(
            "/v1/memory", data=json.dumps({"key": "k", "value": "v"}),
            headers=_auth())
        assert written.status == 200, await written.text()
        assert (await written.json())["ok"] is True

        removed = await client.delete(
            "/v1/memory", data=json.dumps({"key": "k"}), headers=_auth())
        assert removed.status == 200, await removed.text()


def test_an_endpoint_with_no_required_field_still_accepts_no_body_at_all(tmp_path):
    """`allow_empty` measured through the stack, not just on a fake request.

    `POST /v1/desktop/ocr` cannot succeed on a headless box, so this asserts
    what it must *not* say: whatever it answers, it must not be the
    body-shape refusal. That distinguishes "got past parsing and hit the
    missing tesseract" from "was refused for having no body", without
    pinning the environment's own failure (#260).
    """
    asyncio.run(_check_bodyless_request(tmp_path))


async def _check_bodyless_request(root):
    async with _running_client(root) as client:
        response = await client.post(
            "/v1/desktop/ocr",
            headers={"Authorization": f"Bearer {TOKEN}"})
        payload = await _payload(response)
        assert "received" not in payload, payload
        assert "JSON object" not in payload.get("error", ""), payload


# --- the document has to admit the new status --------------------------

def test_every_operation_with_a_json_body_documents_400(spec):
    """Answering an undocumented status would replace one lie with another.

    Schemathesis -- the tool that found this -- reports an undocumented
    status code as a failure in its own right, so this is also what keeps
    the fix from arriving red under the gate it exists to enable.
    """
    undocumented = sorted(
        f"{method.upper()} {path}"
        for path, method, operation in _json_body_operations(spec)
        if "400" not in operation.get("responses", {})
    )
    assert undocumented == [], f"these can answer 400 but do not say so: {undocumented}"


def test_the_documented_400_schema_declares_the_received_field(spec):
    """A field only the prose mentions is not part of the contract.

    Every generated client drops an undeclared field on deserialisation, so
    `received` might as well not exist unless the schema names it.

    Operations that already documented a 400 of their own are exempt: theirs
    is more specific than this generator knows, and it is left alone
    deliberately.
    """
    marker = "The request body is not a JSON object"
    for path, method, operation in _json_body_operations(spec):
        response = operation["responses"]["400"]
        if marker not in response.get("description", ""):
            continue
        schema = response["content"]["application/json"]["schema"]
        assert "received" in schema["properties"], f"{method} {path}"
        # Declared but not required, because the same 400 answers a body
        # that is not JSON at all, where there is no type to name.
        assert "received" not in schema["required"], f"{method} {path}"


def test_the_documented_types_are_exactly_the_ones_the_helper_can_report(spec):
    """The enum and the lookup table have to be one fact, not two.

    They are written in different files, so a JSON type added to one and
    forgotten in the other would leave the document claiming a set of values
    the server never sends -- or worse, sending one it never claimed.
    """
    from arena.handler_helpers import _JSON_TYPE_NAMES

    documented: set[str] = set()
    marker = "The request body is not a JSON object"
    for _path, _method, operation in _json_body_operations(spec):
        response = operation["responses"]["400"]
        if marker not in response.get("description", ""):
            continue
        schema = response["content"]["application/json"]["schema"]
        documented |= set(schema["properties"]["received"]["enum"])
    assert documented == set(_JSON_TYPE_NAMES.values())


def test_the_body_shape_400_is_not_claimed_where_no_json_body_is_read(spec):
    """Sprayed too wide is the same untruth pointing the other way.

    A GET has no body to be the wrong shape, and `/v1/exec/script` takes a
    raw script where `false` is valid input. Documenting the refusal there
    would have clients handling a branch that never arrives -- the mistake
    Greptile caught in the #254 draft.
    """
    marker = "The request body is not a JSON object"
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if not isinstance(operation, dict):
                continue
            description = operation.get("responses", {}).get("400", {}).get("description", "")
            if marker not in description:
                continue
            content = operation.get("requestBody", {}).get("content", {})
            assert "application/json" in content, f"{method.upper()} {path}"


# --- and the shape must not come back ----------------------------------

_HAND_ROLLED = re.compile(r"await request\.json\(\)")


def test_the_number_of_hand_rolled_body_reads_only_goes_down():
    """A ratchet, because this is the third recurrence of one pattern.

    `safe_extract`, then `safe_int` in #254, now `parse_json_body`: each
    time the helper existed and the call sites predated it, and each time
    nothing noticed until a fuzzer did. Counting is crude but it is the only
    check that fires on the *next* handler rather than on this one.

    The remaining reads are on endpoints the OpenAPI document does not
    describe, plus `arena/mcp/handlers.py`, which is correct to read a bare
    array: JSON-RPC batches are arrays by specification. If you have a
    genuine need for another one, raise the number here and say why.
    """
    remaining = sorted(
        (path, len(_HAND_ROLLED.findall(path.read_text(encoding="utf-8"))))
        for path in Path("arena").rglob("*.py")
        if _HAND_ROLLED.search(path.read_text(encoding="utf-8"))
    )
    total = sum(count for _path, count in remaining)
    assert total <= 67, (
        f"{total} hand-rolled `await request.json()` reads, was 67. "
        "Use json_object_body(request) instead: it refuses a non-object body "
        "with a 400 rather than letting `.get` raise a 500 (#259). "
        f"Per file: {[(str(p), n) for p, n in remaining]}"
    )

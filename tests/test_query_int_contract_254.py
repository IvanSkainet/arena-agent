"""A caller's typo must not be reported as the server breaking (#254).

Measured on the operator's live bridge at v4.170.0, with a valid token::

    GET /v1/mission/catalog?offset=null
      -> 500 {"ok": false,
              "error": "ValueError: invalid literal for int() with base 10: 'null'",
              "error_type": "ValueError"}
    GET /v1/mission/catalog?limit=abc     -> 500, same shape
    GET /v1/mission/schedules?limit=null  -> 500, same shape

Two defects in one response. The status blames the server for a malformed
request, so retry logic waits and the `/v1/status` error counter climbs for
something the bridge did nothing wrong in. And the body names a Python
builtin, which is implementation detail crossing the API boundary.

The third endpoint listed in #254, `GET /v1/desktop/screenshot?max_width=0`,
did *not* reproduce: measured against the same live bridge it answers 200.
`arena/desktop/screenshot.py` treats a falsy `max_width` as "no resize", so
zero takes the untransformed path. That row of the issue is wrong, and this
module pins the endpoint anyway -- via the sweep below -- so a future change
cannot quietly make it true.

The sweep is the part that matters. Fixing three call sites is worth little
if the next handler written reaches for `int(request.query[...])` again:
grep found the same shape in fourteen other places, and every one of those
had already been wrapped in a try/except by hand. The property tested here
is the one the issue asks for -- no documented operation answers 5xx to a
syntactically valid request -- driven through the real aiohttp stack.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import unified_bridge as ub
from arena.handler_helpers import QueryParamError, query_int
from arena.public.openapi import build_openapi_spec

TOKEN = "query-int-contract-token"

# Values a client actually sends by accident, plus the ones a fuzzer sends
# on purpose. Every one of them is a legal query string: the HTTP request is
# well formed, only the value is not an integer.
#
# Two near-misses are deliberately absent. `int(" 1")` is 1 and
# `int("\uff10")` -- a fullwidth zero -- is 0, because Python strips
# whitespace and accepts any Unicode decimal digit. Listing them as bad
# input would have tested Python's parser rather than this code, and both
# failed the first run of this module by being accepted, correctly.
# So did `"9" * 400`: Python has no int ceiling, so a 400-digit number is a
# number.
BAD_INTS = ("null", "abc", "", "1.5", "1e999", "+", "0x10", "--1", "1,2")


@pytest.fixture(scope="module")
def spec() -> dict:
    return build_openapi_spec(
        SimpleNamespace(version="test", hostname=lambda: "h", bridge_port=lambda: 8765)
    )


def _concrete_get_operations(spec: dict) -> Iterator[tuple[str, dict]]:
    """Every GET the document describes, minus the templated paths.

    A templated path needs an id that exists on the machine running the
    test, which is a different problem from parsing a query string.
    """
    for path, item in spec["paths"].items():
        operation = item.get("get")
        if operation and "{" not in path:
            yield path, operation


def _query_parameter_types(operation: dict) -> Iterator[tuple[str, str | None]]:
    for parameter in operation.get("parameters", []):
        if parameter.get("in") == "query":
            yield parameter["name"], parameter.get("schema", {}).get("type")


def _integer_query_parameters(spec: dict) -> list[tuple[str, str]]:
    """Every (path, parameter) the document says takes an integer via GET."""
    return [
        (path, name)
        for path, operation in _concrete_get_operations(spec)
        for name, declared in _query_parameter_types(operation)
        if declared == "integer"
    ]


# --- the helper in isolation -------------------------------------------

class _FakeRequest:
    def __init__(self, **query: str) -> None:
        self.query = dict(query)


def test_query_int_reads_a_good_value():
    assert query_int(_FakeRequest(limit="7"), "limit", default=50) == 7


def test_missing_and_empty_both_mean_unspecified():
    """`?offset=` must keep meaning "use the default", as it did before.

    The replaced expression was `int(query.get("offset", [0])[0] or 0)`: the
    `or` swallowed the empty string. Losing that would turn a working
    request into a 400 -- a regression hiding inside a bug fix.
    """
    assert query_int(_FakeRequest(), "offset", default=3) == 3
    assert query_int(_FakeRequest(offset=""), "offset", default=3) == 3


def test_negative_and_zero_still_pass_through_untouched():
    """No range checking. `?limit=-1` answers 200 today; it still must.

    Measured on the live bridge: `/v1/mission/catalog?limit=-1` returns
    `{"ok": true, ..., "limit": 1}` because a lower layer already clamps.
    Refusing it here would be a behaviour change smuggled in with a fix.
    """
    assert query_int(_FakeRequest(limit="-1"), "limit", default=50) == -1
    assert query_int(_FakeRequest(limit="0"), "limit", default=50) == 0


@pytest.mark.parametrize("bad", [b for b in BAD_INTS if b != ""])
def test_query_int_refuses_rather_than_raising_valueerror(bad):
    with pytest.raises(QueryParamError) as caught:
        query_int(_FakeRequest(limit=bad), "limit", default=50)
    assert caught.value.param == "limit"


def test_the_message_names_the_parameter_and_not_the_value():
    """The caller needs to know *which* field; echoing the value reflects it."""
    error = QueryParamError("offset")
    assert "offset" in str(error)


def test_query_param_error_is_a_valueerror():
    """Any handler that already catches ValueError keeps its own behaviour.

    Fourteen call sites do their own `except ValueError: use_default`. If
    QueryParamError were not a ValueError, adopting the helper in one of them
    would silently change its semantics from "default quietly" to "400".
    """
    assert issubclass(QueryParamError, ValueError)


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
    """A live in-process bridge, torn down whatever happens.

    Three tests need one, and the teardown has three obligations that are
    each easy to forget: close the server, restore the logger, and empty the
    per-IP rate-limit store so the next test is not throttled by this one.
    """
    log = logging.getLogger("arena-bridge")
    previous = log.level
    log.setLevel(logging.CRITICAL)  # a deliberate 500 logs a traceback
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
    return {"Authorization": f"Bearer {TOKEN}"}


def test_no_documented_endpoint_answers_5xx_to_a_bad_query_int(spec, tmp_path):
    """The property #254 asks for, over every integer parameter in the document.

    asyncio.run rather than a pytest-asyncio marker: this repo does not
    depend on the plugin, and --strict-markers turns an unknown marker into
    a collection error.
    """
    asyncio.run(_sweep(spec, tmp_path))


async def _is_serviceable(client: TestClient, path: str) -> bool:
    """Can this endpoint answer at all here, with no query string?

    /v1/desktop/screenshot returns 500 "No screenshot tool available" on a
    headless CI box, and a 500 from an endpoint that cannot run says nothing
    about how it parses integers. Asking the endpoint beats an exclusion
    list, which would go stale the moment the environment changed -- and on
    the operator's machine, where screenshot works, it really is tested.
    """
    control = await client.get(path, headers=_auth())
    return control.status < 500


async def _bad_value_faults(
    client: TestClient, path: str, name: str,
) -> tuple[list[str], list[str]]:
    """(crashed, leaked) for one parameter across every bad value."""
    crashed, leaked = [], []
    for bad in BAD_INTS:
        response = await client.get(path, params={name: bad}, headers=_auth())
        where = f"GET {path}?{name}={bad!r}"
        if response.status >= 500:
            crashed.append(f"{where} -> {response.status} {(await response.text())[:200]}")
        elif _error_type_of(await _payload(response)) is not None:
            leaked.append(f"{where} -> {_error_type_of(await _payload(response))}")
    return crashed, leaked


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

    Since the fix, no documented endpoint returns `error_type` at all, so
    the sweep's leak arm never fires on green code. Pin it directly, or the
    arm could be broken and the sweep would go on passing.
    """
    assert _error_type_of({"ok": False, "error_type": "ValueError"}) == "ValueError"
    assert _error_type_of({"ok": False, "error": "query parameter 'x'"}) is None
    assert _error_type_of({}) is None


async def _sweep(spec, root):
    targets = _integer_query_parameters(spec)
    assert targets, "the document declares no integer query parameters -- sweep is vacuous"

    crashed, leaked, skipped = [], [], set()
    async with _running_client(root) as client:
        for path, name in targets:
            if not await _is_serviceable(client, path):
                skipped.add(path)
                continue
            faults, leaks = await _bad_value_faults(client, path, name)
            crashed += faults
            leaked += leaks

    assert crashed == [], (
        "a malformed query integer must not be reported as a server fault: "
        + "; ".join(crashed)
    )
    assert leaked == [], (
        "the error envelope must not name the Python exception class: "
        + "; ".join(leaked)
    )
    # A sweep that skipped everything would pass in silence. The two
    # endpoints #254 was filed about need no hardware and must always run.
    for required in ("/v1/mission/catalog", "/v1/mission/schedules"):
        assert required not in skipped, (
            f"{required} refused its own control request, so the sweep never "
            f"tested it. Skipped: {sorted(skipped)}"
        )


def test_every_documented_400_is_one_the_server_will_actually_give(spec, tmp_path):
    """The other half of #89's lesson: the document says it, the server does it.

    Greptile caught the first draft of this claiming a parse-failure 400 for
    any non-string query parameter, including `number` and `boolean` ones
    whose handlers quietly fall back to a default. That is the same untruth
    as an undocumented status, pointing the other way -- a client handling a
    branch that never arrives. The generated 400 is now integer-only, and
    this test is what stops it drifting back: every operation that carries
    the claim has to honour it under a real request.
    """
    asyncio.run(_check_documented_400s(spec, tmp_path))


async def _check_documented_400s(spec, root):
    wrong, skipped = [], set()
    async with _running_client(root) as client:
        for path, name in _integer_query_parameters(spec):
            if not await _is_serviceable(client, path):
                skipped.add(path)
                continue
            response = await client.get(path, params={name: "abc"}, headers=_auth())
            payload = await _payload(response)
            # The status alone is not enough. /v1/recall answers 400 for a
            # missing `q` too, so a handler that went back to swallowing a
            # bad `top` would still look right here. The refusal has to be
            # about *this* parameter.
            if response.status != 400 or payload.get("param") != name:
                wrong.append(
                    f"GET {path}?{name}=abc -> {response.status} {payload}")
    assert wrong == [], (
        "these operations document a parse-failure 400 they do not give: "
        + "; ".join(wrong)
    )
    for required in ("/v1/mission/catalog", "/v1/mission/schedules", "/v1/recall"):
        assert required not in skipped, f"never checked {required}: {sorted(skipped)}"


def test_the_three_measured_endpoints_answer_400_and_name_the_parameter(tmp_path):
    """Not just "no 5xx" -- the replacement answer has to be the useful one.

    A handler that swallowed the bad value and returned 200 would also pass
    the sweep above while telling the client nothing.
    """
    asyncio.run(_check_refusals(tmp_path))


MEASURED_500s = [
    ("/v1/mission/catalog", "offset", "null"),
    ("/v1/mission/catalog", "limit", "abc"),
    ("/v1/mission/schedules", "limit", "null"),
]


def _assert_useful_refusal(response, payload: dict, name: str, bad: str) -> None:
    where = f"{name}={bad}"
    assert response.status == 400, f"{where} -> {response.status}"
    assert payload["ok"] is False, where
    assert payload["param"] == name, f"{where}: {payload}"
    assert name in payload["error"], f"{where}: {payload}"
    assert "error_type" not in payload, f"{where}: {payload}"
    assert bad not in payload["error"], f"{where}: the offending value is reflected back"


async def _check_refusals(root):
    async with _running_client(root) as client:
        for path, name, bad in MEASURED_500s:
            response = await client.get(path, params={name: bad}, headers=_auth())
            _assert_useful_refusal(response, await response.json(), name, bad)


def test_a_repeated_parameter_still_takes_the_first_value(tmp_path):
    """Flagged in review as a precedence change. Measured, it is not one.

    The replaced expression read `parse_qs(qs)["limit"][0]`; the helper reads
    `request.query.get("limit")`. Both return the *first* occurrence -- and
    a MultiDict does have every occurrence to choose from, so the question
    is real. `?limit=5&limit=abc` therefore still parses 5, rather than
    tripping over the trailing junk and turning a working request into a 400.
    """
    asyncio.run(_check_repeated_parameter(tmp_path))


async def _check_repeated_parameter(root):
    async with _running_client(root) as client:
        response = await client.get(
            "/v1/mission/catalog?limit=5&limit=abc", headers=_auth())
        assert response.status == 200, await response.text()
        assert (await response.json())["limit"] == 5


def test_the_valid_request_still_works(tmp_path):
    """The refusal path is worthless if it also refuses good input."""
    asyncio.run(_check_happy_path(tmp_path))


async def _check_happy_path(root):
    async with _running_client(root) as client:
        for query in ({"limit": "5", "offset": "0"}, {"offset": ""}, {}):
            response = await client.get(
                "/v1/mission/catalog", params=query, headers=_auth())
            assert response.status == 200, f"{query} -> {response.status}"


# --- the document has to admit the new status --------------------------

def test_every_operation_with_an_integer_query_param_documents_400(spec):
    """Answering an undocumented 400 would replace one lie with another.

    Schemathesis -- the tool that found #254 -- reports an undocumented
    status code as a failure in its own right, so this is also what stops
    the fix from arriving red under the gate it is meant to enable.
    """
    undocumented = sorted({
        path for path, _name in _integer_query_parameters(spec)
        if "400" not in spec["paths"][path]["get"].get("responses", {})
    })
    assert undocumented == [], f"these can now answer 400 but do not say so: {undocumented}"


def test_the_generated_400_lands_exactly_on_the_integer_operations(spec):
    """Exactly: neither missing where it belongs, nor sprayed where it does not.

    An earlier draft attached it to every non-string query parameter, which
    swept in `number` and `boolean` ones whose handlers still fall back to a
    default -- documenting a refusal that never comes. A set comparison,
    rather than two one-directional checks, is what makes both mistakes
    visible at once.
    """
    marker = "could not be parsed as an integer"
    expected = {path for path, _name in _integer_query_parameters(spec)}
    claimed = {
        path for path, operation in _concrete_get_operations(spec)
        if marker in json.dumps(operation.get("responses", {}).get("400", {}))
    }
    assert claimed == expected, (
        f"claimed but does not parse an integer: {sorted(claimed - expected)}; "
        f"parses an integer but does not claim: {sorted(expected - claimed)}"
    )

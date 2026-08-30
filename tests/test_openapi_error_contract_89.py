"""Every authenticated operation must document the errors it can actually return (#89).

Measured on 221d2742: of 67 documented operations, 62 of the 63 behind
authentication declared no 401 at all, and 66 declared no schema for their
success body. A caller generating a client from that document would model
only the happy path of an endpoint that refuses most requests.

The three universal responses are generated rather than hand-written, because
they are not per-endpoint facts. They follow from shared machinery:

* ``authed()`` (arena/handler_helpers.py) calls ``ctx.require_auth`` before
  every wrapped handler and converts uncaught exceptions into a 500 envelope.
* ``require_auth()`` (arena/auth/runtime.py) returns 401 for a missing or bad
  credential and 429 once an IP fails ten times inside sixty seconds.

The tests below pin both halves: that the document says it, and -- the half
that matters -- that the server actually does it.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import unified_bridge as ub
from arena.public.openapi import (
    _PUBLIC_PATHS,
    _SUCCESS_SCHEMAS,
    _apply_universal_responses,
    build_openapi_spec,
)

_METHODS = ("get", "post", "put", "delete", "patch")


@pytest.fixture(scope="module")
def spec() -> dict:
    return build_openapi_spec(
        SimpleNamespace(version="test", hostname=lambda: "h", bridge_port=lambda: 8765)
    )


def _operations(spec: dict):
    return [(p, m, o) for p, item in spec["paths"].items()
            for m, o in item.items() if m in _METHODS]


def _authenticated(spec: dict):
    return [(p, m, o) for p, m, o in _operations(spec) if p not in _PUBLIC_PATHS]


@pytest.mark.parametrize("code", ["401", "429", "500"])
def test_every_authenticated_operation_documents_the_universal_errors(spec, code):
    missing = [f"{m.upper()} {p}" for p, m, o in _authenticated(spec)
               if code not in o.get("responses", {})]
    assert missing == [], f"{len(missing)} operations do not document {code}: {missing[:10]}"


def test_public_operations_are_not_given_a_false_401(spec):
    """Documenting a refusal on a route that never refuses would be a new lie."""
    wrong = [f"{m.upper()} {p}" for p, m, o in _operations(spec)
             if p in _PUBLIC_PATHS and "401" in o.get("responses", {})]
    assert wrong == [], f"public endpoints must not claim to require auth: {wrong}"


def test_error_responses_carry_a_schema_not_just_prose(spec):
    """A description a generator cannot read is documentation, not a contract."""
    for p, m, o in _authenticated(spec):
        for code in ("401", "500"):
            body = o["responses"][code]
            schema = body.get("content", {}).get("application/json", {}).get("schema")
            assert schema, f"{m.upper()} {p} {code} has no JSON schema"
            assert "ok" in schema["properties"], f"{m.upper()} {p} {code} lacks ok"
            assert "error" in schema["properties"], f"{m.upper()} {p} {code} lacks error"


def test_the_429_documents_retry_after(spec):
    """The throttle sets Retry-After; a client that cannot see it will hammer."""
    for p, m, o in _authenticated(spec):
        assert "Retry-After" in o["responses"]["429"].get("headers", {}), \
            f"{m.upper()} {p} does not document Retry-After on 429"


def test_generator_never_overwrites_a_specific_response():
    """An endpoint that documents its own 401 keeps its own wording."""
    spec = {"paths": {"/v1/thing": {"get": {"responses": {
        "200": {"description": "ok"},
        "401": {"description": "bespoke and more precise"},
    }}}}}
    _apply_universal_responses(spec)
    got = spec["paths"]["/v1/thing"]["get"]["responses"]
    assert got["401"]["description"] == "bespoke and more precise"
    assert "429" in got and "500" in got


def test_generator_skips_public_paths():
    spec = {"paths": {"/health": {"get": {"responses": {"200": {"description": "ok"}}}}}}
    _apply_universal_responses(spec)
    assert set(spec["paths"]["/health"]["get"]["responses"]) == {"200"}


def test_public_path_list_matches_the_enforced_auth_allow_list():
    """_PUBLIC_PATHS must not drift from the guard that is enforced by execution.

    tests/test_auth_surface_guard.py walks every registered route and requires
    a refusal from each one absent from its allow-list. If this module's list
    grows an entry that guard does not have, the document would excuse a route
    that really does demand a credential.
    """
    from tests.test_auth_surface_guard import PROTOCOL_ENVELOPE, PUBLIC_BY_DESIGN
    enforced = set(PUBLIC_BY_DESIGN) | set(PROTOCOL_ENVELOPE)
    extra = _PUBLIC_PATHS - enforced
    assert extra == set(), (
        f"_PUBLIC_PATHS claims these need no auth, but the enforced guard "
        f"disagrees: {sorted(extra)}"
    )


# ---------------------------------------------------------------------
# The half that matters: does the server behave the way the document now
# promises? Driven in-process through the real aiohttp stack, so the
# per-IP rate limiter cannot distort the result.
# ---------------------------------------------------------------------

def _build_app() -> web.Application:
    app = ub.make_app({
        "token": "contract-token-never-presented", "profile": "owner-shell",
        "root": Path("/tmp"), "active_exec": 0, "max_concurrent": 3,
        "audit": "audit", "timeout": 60, "max_timeout": 3600,
        "max_output": 2000000, "allow_any_cwd": False,
        "semaphore": asyncio.Semaphore(1),
    })
    # Lifecycle hooks tear down the shared executor and poison later tests;
    # routing and auth do not need the background workers.
    app.on_startup.clear()
    app.on_cleanup.clear()
    app.on_shutdown.clear()
    return app


def test_documented_401_is_what_the_server_actually_does(spec):
    """No operation documented as authenticated may serve data without a token.

    The loop is driven with asyncio.run rather than pytest.mark.asyncio: this
    repo does not depend on pytest-asyncio, and --strict-markers turns an
    unknown marker into a collection error. Caught by running on the target
    machine -- it passed in a sandbox that happened to have the plugin.
    """
    asyncio.run(_probe_every_authenticated_operation(spec))


async def _probe_every_authenticated_operation(spec):
    log = logging.getLogger("arena-bridge")
    previous = log.level
    log.setLevel(logging.ERROR)  # the sweep fails auth ~60 times by design
    server = TestServer(_build_app())
    await server.start_server()
    client = TestClient(server)
    await client.start_server()
    refusal, benign = {401, 403, 429}, {400, 404, 405, 422}
    leaked = []
    try:
        for path, method, _op in _authenticated(spec):
            if "{" in path:
                continue  # templated paths are covered by the auth surface guard
            response = await client.request(
                method.upper(), path, json=None if method == "get" else {},
            )
            if response.status not in refusal | benign:
                leaked.append(f"{method.upper()} {path} -> {response.status}")
    finally:
        await client.close()
        await server.close()
        log.setLevel(previous)
        rl = getattr(ub, "_rate_limit_store", None)
        if isinstance(rl, dict):
            rl.clear()
    assert leaked == [], (
        "these operations document a 401 but served a credential-less caller: "
        f"{leaked}"
    )


# ---------------------------------------------------------------------
# Success-body schemas: pinned against real responses, because a schema
# nobody checks is a claim that drifts the first time a handler changes.
# ---------------------------------------------------------------------

def test_every_success_schema_targets_a_documented_operation():
    """A schema for a path missing from `paths` is silently inert.

    Two entries were written this way during #89 (/v2/health, /v1/metrics),
    applied to nothing, and the count came out two lower than intended.
    """
    spec = build_openapi_spec(
        SimpleNamespace(version="t", hostname=lambda: "h", bridge_port=lambda: 1)
    )
    orphans = [f"{m.upper()} {p}" for (p, m) in _SUCCESS_SCHEMAS
               if not spec.get("paths", {}).get(p, {}).get(m)]
    assert orphans == [], f"success schemas that apply to no documented operation: {orphans}"


def test_success_schemas_match_what_the_endpoints_really_return(spec):
    """Every documented required key must be present, and typed, in a real response."""
    asyncio.run(_check_success_schemas(spec))


async def _check_success_schemas(spec):
    json_type = {
        "boolean": bool, "string": str, "integer": int,
        "number": (int, float), "object": dict, "array": list,
    }
    server = TestServer(_build_app())
    await server.start_server()
    client = TestClient(server)
    await client.start_server()
    problems = []
    try:
        for (path, method) in _SUCCESS_SCHEMAS:
            if method != "get":
                continue  # only side-effect-free probes belong in this test
            operation = spec["paths"][path][method]
            schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
            response = await client.get(path)
            if response.status != 200:
                problems.append(f"GET {path} -> {response.status}")
                continue
            body = await response.json()
            for key in schema["required"]:
                if key not in body:
                    problems.append(f"GET {path}: documents required '{key}', absent")
                    continue
                declared = schema["properties"][key]["type"]
                if isinstance(declared, list):
                    continue  # nullable unions: presence is the contract
                expected = json_type[declared]
                if not isinstance(body[key], expected) or (
                    declared != "boolean" and isinstance(body[key], bool)
                ):
                    problems.append(
                        f"GET {path}: '{key}' documented {declared}, "
                        f"got {type(body[key]).__name__}"
                    )
    finally:
        await client.close()
        await server.close()
    assert problems == [], f"documented success schemas contradict real responses: {problems}"

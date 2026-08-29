"""The served OpenAPI document must not fall further behind the route registry (#204).

Measured on eb925fa3 against the running bridge: the registry declares 291
routes, the document describes 64. Both artefacts had passing tests -- the
route guards proved every registered route was wired, the OpenAPI tests proved
the document was well-formed. Nothing read both, so the two drifted until 227
endpoints were invisible to anyone reading the spec, including
``POST /v1/token/regenerate``.

These tests pin the comparison itself, so the ratchet cannot go blind.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RATCHET = REPO_ROOT / "scripts" / "openapi_parity_ratchet.py"


def _load_ratchet():
    spec = importlib.util.spec_from_file_location("openapi_parity_ratchet", RATCHET)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ratchet():
    return _load_ratchet()


def test_the_ratchet_script_exists_and_is_executable_as_a_module():
    assert RATCHET.is_file(), f"{RATCHET} is missing; CI references it"


def test_ratchet_passes_on_the_current_tree():
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(RATCHET)], capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, f"parity ratchet is red on a clean tree:\n{proc.stdout}{proc.stderr}"


def test_registry_reader_sees_the_whole_registry(ratchet):
    """A reader that returns a handful of routes would make the gate decorative."""
    routes = ratchet.registry_routes()
    assert len(routes) >= ratchet.MIN_REGISTRY_ROUTES, (
        f"only {len(routes)} routes read from the registry"
    )
    assert ("POST", "/v1/exec") in routes
    assert ("POST", "/v1/exec/script") in routes


def test_openapi_reader_sees_the_document(ratchet):
    ops = ratchet.documented_operations()
    assert len(ops) >= ratchet.MIN_DOCUMENTED_OPERATIONS
    assert ("POST", "/v1/exec") in ops
    assert ("GET", "/health") in ops


def test_no_ghost_operations(ratchet):
    """The spec must never promise an endpoint that is not registered.

    This is #125: a caller that follows the document gets a 404. Unlike the
    undocumented count, this has no baseline -- it is zero or the gate is red.
    """
    ghosts = ratchet.documented_operations() - ratchet.registry_routes()
    assert ghosts == set(), f"documented but not registered: {sorted(ghosts)}"


def test_undocumented_count_is_at_or_below_the_ceiling(ratchet):
    undocumented = ratchet.registry_routes() - ratchet.documented_operations()
    assert len(undocumented) <= ratchet.MAX_UNDOCUMENTED, (
        f"{len(undocumented)} undocumented routes exceeds the ceiling of "
        f"{ratchet.MAX_UNDOCUMENTED}; document the new route in arena/public/openapi.py"
    )


def test_ceiling_is_not_slack(ratchet):
    """The ceiling must track reality, not sit far above it.

    A ceiling well above the real count silently permits new undocumented
    routes -- exactly the drift this gate exists to stop.
    """
    undocumented = ratchet.registry_routes() - ratchet.documented_operations()
    assert ratchet.MAX_UNDOCUMENTED - len(undocumented) <= 5, (
        f"MAX_UNDOCUMENTED is {ratchet.MAX_UNDOCUMENTED} but only "
        f"{len(undocumented)} routes are undocumented; lower the ceiling"
    )


def test_path_normalisation_reconciles_aiohttp_and_openapi_syntax(ratchet):
    """``{path:.*}`` and ``{path}`` describe the same operation."""
    assert ratchet._normalise("/gui/assets/{path:.*}") == "/gui/assets/{path}"
    assert ratchet._normalise("/v1/agents/{agent_id}") == "/v1/agents/{agent_id}"
    assert ratchet._normalise("/health") == "/health"


@pytest.mark.parametrize("route", [
    ("POST", "/v1/token/regenerate"),
    ("POST", "/v1/exec/script"),
    ("POST", "/v1/exec/stream"),
])
def test_security_relevant_routes_are_documented(ratchet, route):
    """Endpoints that rotate credentials or execute code must be discoverable.

    These were undocumented when #204 was filed. An operator reading the spec
    could not learn that the endpoint rotating their own token existed.
    """
    assert route in ratchet.documented_operations(), (
        f"{route[0]} {route[1]} is registered but absent from the OpenAPI document"
    )

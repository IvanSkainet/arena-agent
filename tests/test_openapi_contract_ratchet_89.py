"""Failure-branch tests for the contract ratchet (#89).

A gate that cannot detect its own disablement is decoration. #204 established
this the hard way: turning off the ceiling check and regressing the path
regex both left the ratchet green. So every guarantee here is exercised by
forcing the condition, not by reading the code.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RATCHET = REPO_ROOT / "scripts" / "openapi_contract_ratchet.py"


def _load_ratchet():
    spec = importlib.util.spec_from_file_location("openapi_contract_ratchet", RATCHET)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def ratchet():
    """Fresh module per test: these tests monkeypatch its constants."""
    return _load_ratchet()


def _spec(paths: dict) -> dict:
    return {"paths": paths}


def test_the_ratchet_script_exists_and_is_executable_as_a_module():
    assert RATCHET.is_file(), f"{RATCHET} is missing; CI references it"


def test_passes_on_the_real_document(ratchet):
    assert ratchet.main() == 0


def test_fails_when_an_authenticated_operation_drops_its_401(ratchet, monkeypatch, capsys):
    broken = {f"/v1/fake{i}": {"get": {"responses": {"429": {}, "500": {}}}}
              for i in range(ratchet.MIN_OPERATIONS + 1)}
    monkeypatch.setattr(ratchet, "_spec", lambda: _spec(broken))
    assert ratchet.main() == 1
    assert "no 401" in capsys.readouterr().out


def test_fails_when_the_reader_returns_almost_nothing(ratchet, monkeypatch, capsys):
    """Guards against a reader change that quietly reports an empty document."""
    monkeypatch.setattr(ratchet, "_spec", lambda: _spec({"/health": {"get": {}}}))
    assert ratchet.main() == 1
    assert "the reader is broken" in capsys.readouterr().out


def test_fails_when_a_success_schema_is_removed(ratchet, monkeypatch, capsys):
    ok = {f"/v1/fake{i}": {"get": {"responses": {"401": {}, "429": {}, "500": {}}}}
          for i in range(ratchet.MIN_OPERATIONS + 1)}
    monkeypatch.setattr(ratchet, "_spec", lambda: _spec(ok))
    monkeypatch.setattr(ratchet, "MIN_SUCCESS_SCHEMAS", 1)
    assert ratchet.main() == 1
    assert "below the floor" in capsys.readouterr().out


def test_reports_when_the_floor_can_be_raised(ratchet, monkeypatch, capsys):
    schema = {"content": {"application/json": {"schema": {"type": "object"}}}}
    improved = {f"/v1/fake{i}": {"get": {"responses": {
        "200": dict(schema), "401": {}, "429": {}, "500": {}}}}
        for i in range(ratchet.MIN_OPERATIONS + 1)}
    monkeypatch.setattr(ratchet, "_spec", lambda: _spec(improved))
    monkeypatch.setattr(ratchet, "MIN_SUCCESS_SCHEMAS", 1)
    assert ratchet.main() == 0
    assert "Raise MIN_SUCCESS_SCHEMAS" in capsys.readouterr().out


def test_public_paths_are_exempt_from_the_error_requirement(ratchet, monkeypatch):
    """Otherwise the gate would demand a 401 from endpoints that never refuse."""
    from arena.public.openapi import _PUBLIC_PATHS
    public = next(iter(_PUBLIC_PATHS))
    paths = {f"/v1/fake{i}": {"get": {"responses": {"401": {}, "429": {}, "500": {}}}}
             for i in range(ratchet.MIN_OPERATIONS + 1)}
    paths[public] = {"get": {"responses": {"200": {"description": "ok"}}}}
    monkeypatch.setattr(ratchet, "_spec", lambda: _spec(paths))
    monkeypatch.setattr(ratchet, "MIN_SUCCESS_SCHEMAS", 0)
    assert ratchet.main() == 0


def test_the_floor_is_not_slack(ratchet):
    """The floor must equal what the document actually achieves.

    Found by sabotage: setting MIN_SUCCESS_SCHEMAS to 0 left every other test
    green, because a floor below reality is satisfied by anything. A ratchet
    with slack is a ratchet that permits silent regression down to the slack
    line -- the exact way the #204 gate was shown to be blind to its own
    weakening. Lowering this constant now requires deleting this test, which
    is a visible act in review.
    """
    spec = ratchet._spec()
    actual = 0
    for _path, item in spec["paths"].items():
        for method, operation in item.items():
            if method not in ("get", "post", "put", "delete", "patch"):
                continue
            responses = operation.get("responses", {})
            success = responses.get("200") or responses.get("201") or {}
            if (success.get("content") or {}).get("application/json", {}).get("schema"):
                actual += 1
    assert ratchet.MIN_SUCCESS_SCHEMAS == actual, (
        f"floor is {ratchet.MIN_SUCCESS_SCHEMAS} but the document achieves {actual}; "
        f"a floor below reality allows regression down to it"
    )

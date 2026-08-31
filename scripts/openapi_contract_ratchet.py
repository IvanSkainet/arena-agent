#!/usr/bin/env python3
"""Gate: documented operations must declare the errors they can actually return (#89).

The parity ratchet (#204) counts routes that appear in the document at all.
This one checks that what IS documented tells the truth about failure.

Measured on 221d2742, before this gate: 67 documented operations, of which 62
of the 63 behind authentication declared no 401, and 66 declared no schema for
their success body. A generated client would model only the happy path of an
endpoint that refuses most callers.

The universal errors (401/429/500) are generated in arena/public/openapi.py
because they follow from shared machinery rather than per-endpoint choices --
see _apply_universal_responses. This script is the ratchet for the part that
cannot be generated: the success-body schemas, which have to be written per
endpoint because only the endpoint knows its own shape.

Success schemas may only increase. Errors are pass/fail, not ratcheted: the
generator makes full coverage cheap, so there is no reason to permit a gap.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Operations whose 2xx body is described by a schema. Raise this as endpoints
# get documented; never lower it. Measured at 221d2742 + the three routes
# documented by #205.
MIN_SUCCESS_SCHEMAS = 3

# A detector that inspects an empty document reports OK forever.
MIN_OPERATIONS = 60

_METHODS = ("get", "post", "put", "delete", "patch")


def _spec() -> dict:
    from arena.public.openapi import build_openapi_spec
    return build_openapi_spec(
        SimpleNamespace(version="0.0.0", hostname=lambda: "localhost",
                        bridge_port=lambda: 8765)
    )


def main() -> int:
    from arena.public.openapi import _PUBLIC_PATHS

    spec = _spec()
    operations = [(p, m, o) for p, item in spec["paths"].items()
                  for m, o in item.items() if m in _METHODS]

    if len(operations) < MIN_OPERATIONS:
        print(f"openapi contract ratchet: FAIL -- only {len(operations)} operations read "
              f"(expected at least {MIN_OPERATIONS}); the reader is broken, not the "
              f"document empty")
        return 1

    authenticated = [(p, m, o) for p, m, o in operations if p not in _PUBLIC_PATHS]
    missing: list[str] = []
    for path, method, operation in authenticated:
        responses = operation.get("responses", {})
        for code in ("401", "429", "500"):
            if code not in responses:
                missing.append(f"{method.upper()} {path}: no {code}")

    if missing:
        print("openapi contract ratchet: FAIL -- authenticated operations that do not "
              "document the errors they can return:")
        for line in missing[:30]:
            print(f"  {line}")
        print()
        print("  These are attached by _apply_universal_responses() in")
        print("  arena/public/openapi.py. If an operation is genuinely public, add it")
        print("  to _PUBLIC_PATHS -- and to the enforced allow-list in")
        print("  tests/test_auth_surface_guard.py, which proves it by execution.")
        return 1

    with_schema = 0
    for _path, _method, operation in operations:
        responses = operation.get("responses", {})
        success = responses.get("200") or responses.get("201") or {}
        if (success.get("content") or {}).get("application/json", {}).get("schema"):
            with_schema += 1

    if with_schema < MIN_SUCCESS_SCHEMAS:
        print(f"openapi contract ratchet: FAIL -- {with_schema} operations describe their "
              f"success body, below the floor of {MIN_SUCCESS_SCHEMAS}. A response schema "
              f"was removed.")
        return 1

    if with_schema > MIN_SUCCESS_SCHEMAS:
        print(f"openapi contract ratchet: OK -- {with_schema} success schemas, above the "
              f"floor of {MIN_SUCCESS_SCHEMAS}.")
        print(f"  Raise MIN_SUCCESS_SCHEMAS to {with_schema} in "
              f"{Path(__file__).name} to lock the improvement in.")
        return 0

    print(f"openapi contract ratchet: OK -- {len(operations)} operations, "
          f"{len(authenticated)} authenticated and all documenting 401/429/500, "
          f"{with_schema} describing their success body (floor {MIN_SUCCESS_SCHEMAS})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

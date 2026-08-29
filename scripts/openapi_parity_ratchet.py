#!/usr/bin/env python3
"""Gate: the served OpenAPI document must not fall further behind the route registry.

``arena/route_registry/registry.py`` is the single place every HTTP route is
declared. ``arena/public/openapi.py`` builds the document served at
``/openapi.json`` from a hand-written ``paths`` dict. Nothing compared the two,
so they drifted: measured against the running bridge, the registry declares 291
routes and the document describes 64 of them -- 22% of the surface.

Both artefacts were internally consistent the whole time. Route-wiring guards
proved every registered route exists; the OpenAPI tests proved the document
parses. Neither read the other, so 227 endpoints -- every ``/v1/mobile/*``
operation, every tunnel transport, ``/v1/admin/*``, ``/v1/control/*``,
``POST /v1/token/regenerate`` -- were invisible to anyone reading the spec.

This is a ratchet, not a pass/fail gate: 227 undocumented routes cannot be
written by hand in one change. The count may shrink, never grow. Adding a route
without documenting it fails here.

Direction matters. A *documented* operation that is not registered ("ghost"
route: the spec promises an endpoint that 404s) is always an error, never
baselined -- that is #125, and it is currently zero.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# The high-water mark. Lower this when routes get documented; never raise it.
# eb925fa3 measured 227. This change documented POST /v1/exec/script,
# POST /v1/exec/stream and POST /v1/token/regenerate -- the credential-rotation
# and code-execution endpoints an operator could not find in the spec.
MAX_UNDOCUMENTED = 224

# A detector that silently compares two empty sets reports OK forever.
# Same failure mode json_shape_ratchet.py guards with MIN_FILES_SCANNED.
MIN_REGISTRY_ROUTES = 250
MIN_DOCUMENTED_OPERATIONS = 50

_HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head", "options"})


def _normalise(path: str) -> str:
    """``/v1/x/{p:.*}`` and ``/v1/x/{p}`` are the same operation.

    aiohttp allows a regex suffix inside a path variable; OpenAPI has no such
    notion. Without this the two artefacts disagree on paths that match the
    same requests, and the ratchet reports drift that does not exist.
    """
    return re.sub(r"\{(\w+):[^}]*\}", r"{\1}", path)


def registry_routes() -> set[tuple[str, str]]:
    from arena.route_registry.registry import ROUTES
    return {(method.upper(), _normalise(path)) for method, path, *_rest in ROUTES}


def documented_operations() -> set[tuple[str, str]]:
    from arena.public.openapi import build_openapi_spec

    # build_openapi_spec only reads .version / .hostname() / .bridge_port()
    # for the info block; none of it affects which paths are described.
    ctx = SimpleNamespace(
        version="0.0.0", hostname=lambda: "localhost", bridge_port=lambda: 8765,
    )
    spec = build_openapi_spec(ctx)
    return {
        (method.upper(), _normalise(path))
        for path, item in spec["paths"].items()
        for method in item
        if method.lower() in _HTTP_METHODS
    }


def main() -> int:
    registered = registry_routes()
    documented = documented_operations()

    if len(registered) < MIN_REGISTRY_ROUTES:
        print(f"openapi parity ratchet: FAIL -- only {len(registered)} routes read from the "
              f"registry (expected at least {MIN_REGISTRY_ROUTES}); the reader is broken, "
              f"not the registry empty")
        return 1
    if len(documented) < MIN_DOCUMENTED_OPERATIONS:
        print(f"openapi parity ratchet: FAIL -- only {len(documented)} operations read from "
              f"the OpenAPI builder (expected at least {MIN_DOCUMENTED_OPERATIONS}); the "
              f"reader is broken, not the document empty")
        return 1

    undocumented = sorted(registered - documented)
    ghosts = sorted(documented - registered)

    if ghosts:
        print("openapi parity ratchet: FAIL -- the document describes operations that are "
              "not registered. Callers following the spec will get 404:")
        for method, path in ghosts:
            print(f"  {method:6s} {path}")
        return 1

    if len(undocumented) > MAX_UNDOCUMENTED:
        added = len(undocumented) - MAX_UNDOCUMENTED
        print(f"openapi parity ratchet: FAIL -- {len(undocumented)} registered routes are "
              f"undocumented, {added} more than the ceiling of {MAX_UNDOCUMENTED}.")
        print()
        print("  A route was added to arena/route_registry/registry.py without a matching")
        print("  entry in arena/public/openapi.py. Document it, or the endpoint ships")
        print("  invisible to every caller that reads the spec.")
        print()
        print("  Undocumented routes (first 40 shown):")
        for method, path in undocumented[:40]:
            print(f"    {method:6s} {path}")
        return 1

    if len(undocumented) < MAX_UNDOCUMENTED:
        print(f"openapi parity ratchet: OK -- {len(undocumented)} undocumented routes, "
              f"below the ceiling of {MAX_UNDOCUMENTED}.")
        print(f"  Lower MAX_UNDOCUMENTED to {len(undocumented)} in {Path(__file__).name} "
              f"to lock the improvement in.")
        return 0

    print(f"openapi parity ratchet: OK -- {len(registered)} registered routes, "
          f"{len(documented)} documented, {len(undocumented)} undocumented "
          f"(ceiling {MAX_UNDOCUMENTED}, no ghost operations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

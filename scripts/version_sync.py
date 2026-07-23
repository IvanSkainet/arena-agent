"""Version-sync guard for the bridge.

There are four places a bridge release version MUST stay in sync:

  1. ``arena/constants.py``               ``VERSION = "X.Y.Z"``
  2. ``pyproject.toml``                   ``version = "X.Y.Z"`` (top-level [project])
  3. ``tests/_version_matrix.py``         last entry of ``BRIDGE_VERSIONS`` tuple
  4. ``tests/_version_matrix.py``         ``LATEST_BRIDGE`` (== ``BRIDGE_VERSIONS[-1]``)

If any of them drifts, the v4.51.x → v4.60.x test files
(``tests/test_extension_v4_5*_*.py``) start failing in
``test_*_version_bumped`` and ``test_version_matrix.py::test_latest_bridge_matches_constants_module``,
the README badge from ``v/release`` shows the wrong tag, and
``dev/bump_version.py`` mis-fires its "already at <X>" guard
on the next bump.

This guard runs in CI and PRs and fails the build the moment
the four drift, before the drift has a chance to land on master.

Why a separate guard
--------------------

``dev/bump_version.py`` does the right thing — it bumps all three
mutable places atomically. The bug is not in the script; the bug
is in *not using* the script. Hand-edits, AI-maintainer pipelines
that update ``pyproject.toml`` first, partial release runs that
fail halfway — every one of them leaves the four places out of
sync. This guard turns "drift" from a "discover on next release"
problem into a "fail the PR that introduced the drift" problem.

Usage
-----

::

    python scripts/version_sync.py
    python scripts/version_sync.py --repo-root .
    python scripts/version_sync.py --json   # machine-readable

Exit code:

- 0 if all four are in sync
- 1 if any drift is detected (printed to stdout / --json)
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_constants(repo_root: Path) -> Optional[str]:
    """Extract ``VERSION = "X.Y.Z"`` from ``arena/constants.py`` via AST."""
    path = repo_root / "arena" / "constants.py"
    try:
        tree = ast.parse(_read(path))
    except SyntaxError:
        return None
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "VERSION"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "VERSION"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def _parse_pyproject(repo_root: Path) -> Optional[str]:
    """Extract the top-level ``[project] version = "X.Y.Z"`` from pyproject.toml.

    Uses regex because pyproject.toml is TOML (not Python) — but the
    pattern is very stable: a top-level line of the form
    ``version = "X.Y.Z"`` after the ``[project]`` section opener.
    """
    path = repo_root / "pyproject.toml"
    src = _read(path)
    in_project = False
    for line in src.splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("[") and stripped.endswith("]"):
            # entered a different section; stop
            break
        if in_project:
            m = re.match(r'^version\s*=\s*"([^"]+)"\s*$', stripped)
            if m:
                return m.group(1)
    return None


def _parse_version_matrix(repo_root: Path) -> Dict[str, Any]:
    """Extract ``BRIDGE_VERSIONS`` and the computed ``LATEST_BRIDGE`` from
    ``tests/_version_matrix.py`` via AST. We read the file, parse it, and
    walk the top-level statements to find the tuple assignment."""
    path = repo_root / "tests" / "_version_matrix.py"
    result: Dict[str, Any] = {"bridge_versions": None, "latest_bridge": None}
    try:
        tree = ast.parse(_read(path))
    except SyntaxError:
        return result

    for node in tree.body:
        if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
            continue
        name = node.target.id
        if name == "BRIDGE_VERSIONS" and isinstance(node.value, ast.Tuple):
            result["bridge_versions"] = [
                el.value
                for el in node.value.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            ]
        elif name == "LATEST_BRIDGE" and isinstance(node.value, ast.Subscript):
            # LATEST_BRIDGE = BRIDGE_VERSIONS[-1] — pull the literal index
            sl = node.value.slice
            if (
                isinstance(node.value.value, ast.Name)
                and node.value.value.id == "BRIDGE_VERSIONS"
                and isinstance(sl, ast.UnaryOp)
                and isinstance(sl.op, ast.USub)
                and isinstance(sl.operand, ast.Constant)
                and isinstance(sl.operand.value, int)
            ):
                idx = -sl.operand.value
                if result["bridge_versions"] is not None and abs(idx) <= len(result["bridge_versions"]):
                    result["latest_bridge"] = result["bridge_versions"][idx]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo-root", default=".", help="Path to the repo root")
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of the default human text",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()

    constants = _parse_constants(repo_root)
    pyproject = _parse_pyproject(repo_root)
    matrix = _parse_version_matrix(repo_root)
    bridge_versions = matrix["bridge_versions"]
    latest_bridge = matrix["latest_bridge"]

    sources = {
        "arena/constants.py": constants,
        "pyproject.toml": pyproject,
        "tests/_version_matrix.py (last BRIDGE_VERSIONS)": (
            bridge_versions[-1] if bridge_versions else None
        ),
        "tests/_version_matrix.py (LATEST_BRIDGE)": latest_bridge,
    }

    defined = {k: v for k, v in sources.items() if v is not None}
    missing = [k for k, v in sources.items() if v is None]
    unique = set(defined.values())
    in_sync = len(unique) == 1 and not missing

    if args.json:
        out = {
            "in_sync": in_sync,
            "sources": sources,
            "unique_values": sorted(unique),
            "missing_sources": missing,
        }
        print(json.dumps(out, indent=2))
        return 0 if in_sync else 1

    print("[version-sync] bridge version across 4 sources:")
    for k, v in sources.items():
        if v is None:
            marker = "FAIL"  # type: ignore[unreachable]
            print(f"  {marker} {k:55s}  <missing>")
        else:
            marker = "OK " if in_sync else "..."
            print(f"  {marker} {k:55s}  {v}")
    if in_sync:
        print(f"[version-sync] OK: all four agree on {next(iter(unique))}")
        return 0

    if missing:
        print(
            f"[version-sync] FAIL: missing source(s) — {', '.join(missing)}"
            " cannot be parsed (SyntaxError or no matching literal?)."
        )
    else:
        print("[version-sync] FAIL: drift detected across the four sources.")
    print(
        "[version-sync] Run `python dev/bump_version.py <X.Y.Z>` to bring"
        " them back in sync, then re-run this guard."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

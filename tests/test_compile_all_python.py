"""v4.63.0 - py_compile every .py in arena/, scripts/, bin/.

Catches the obvious failure mode of "I committed a file with
a syntax error and CI didn't notice until someone ran the
tests". A ``SyntaxError`` at the top of any module means the
bridge can't even *import* that module — and the existing
test suite only imports a subset of ``arena/`` (it walks
through the public surface). A typo in a seldom-imported
module can land on master undetected.

This test is a thin wrapper over ``py_compile``: it walks the
three production directories, byte-compiles every ``.py``,
and fails on the first ``SyntaxError``. It does not run the
modules, so it's safe to invoke on any platform.

The test ignores ``__pycache__`` and excludes ``tests/`` (which
has its own test-suite-driven compilation check via pytest's
collection phase).
"""
from __future__ import annotations

import py_compile
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]


def _python_sources() -> list[Path]:
    out: list[Path] = []
    for subdir in ("arena", "scripts", "bin"):
        root = REPO / subdir
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            # Skip the bytecode cache and any future build dirs.
            if any(part == "__pycache__" for part in p.parts):
                continue
            if p.name.startswith(".") or p.suffix != ".py":
                continue
            out.append(p)
    return sorted(out)


def test_every_production_python_file_compiles() -> None:
    """Byte-compile every .py in arena/, scripts/, bin/. A
    SyntaxError here means the file cannot be imported at all,
    which would break the bridge at startup. We fail fast on
    the first error to keep the CI log short.
    """
    sources = _python_sources()
    if not sources:
        pytest.skip("no production python sources found (running outside the repo)")
    assert len(sources) > 100, (
        f"only {len(sources)} python sources found in arena/ + scripts/ + bin/;"
        " expected several hundred. The include paths may have changed."
    )

    failures: list[tuple[Path, str]] = []
    for path in sources:
        try:
            py_compile.compile(
                str(path),
                doraise=True,
            )
        except py_compile.PyCompileError as e:
            failures.append((path, str(e).splitlines()[-1] if e.msg else str(e)))

    if failures:
        msg = [f"{len(failures)} of {len(sources)} production python files fail to compile:"]
        for path, err in failures[:10]:
            msg.append(f"  {path.relative_to(REPO)}: {err}")
        if len(failures) > 10:
            msg.append(f"  ... and {len(failures) - 10} more")
        pytest.fail("\n".join(msg))

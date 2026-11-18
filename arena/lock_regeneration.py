"""Order root lock inputs by their local generated-constraint dependencies."""
from __future__ import annotations

import shlex
from pathlib import Path


def _constraint_target(line: str) -> str | None:
    tokens = shlex.split(line, comments=True)
    if not tokens:
        return None
    if tokens[0] in ("-c", "--constraint"):
        if len(tokens) != 2:
            raise ValueError(f"invalid constraint directive: {line}")
        return tokens[1]
    if tokens[0].startswith("--constraint="):
        if len(tokens) != 1 or not tokens[0].split("=", 1)[1]:
            raise ValueError(f"invalid constraint directive: {line}")
        return tokens[0].split("=", 1)[1]
    if tokens[0].startswith("-c"):
        if len(tokens) != 1:
            raise ValueError(f"invalid constraint directive: {line}")
        return tokens[0][2:]
    return None


def regeneration_order(root: Path) -> list[str]:
    """Fail closed on missing generators, nonlocal constraints, and cycles.

    Only root requirements-*.in / .lock pairs participate. All prerequisites
    are visited before their consumers, independent of alphabetical order.
    No resolver, network request, or repository-supplied program is executed.
    """
    inputs = {path.name: path for path in root.glob("requirements-*.in")}
    dependencies: dict[str, set[str]] = {}
    for name, path in sorted(inputs.items()):
        dependencies[name] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            target = _constraint_target(line)
            if target is None:
                continue
            constraint = Path(target)
            if constraint.name != target or constraint.suffix not in (".lock", ".txt"):
                raise ValueError(f"{name}: unsupported constraint path {target!r}")
            producer = constraint.with_suffix(".in").name
            if producer not in inputs:
                raise ValueError(f"{name}: no generator for {target}")
            dependencies[name].add(producer)
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError(f"constraint dependency cycle at {name}")
        if name in visited:
            return
        visiting.add(name)
        for dependency in sorted(dependencies[name]):
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)

    for name in sorted(inputs):
        visit(name)
    return ordered

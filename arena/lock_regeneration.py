"""Order root lock inputs by their local generated-constraint dependencies."""
from __future__ import annotations

import shlex
from graphlib import CycleError, TopologicalSorter
from pathlib import Path


def _constraint_target(line: str) -> str | None:
    tokens = shlex.split(line, comments=True)
    if not tokens:
        return None
    first = tokens[0]
    if first in ("-c", "--constraint"):
        return _separate_constraint(tokens, line)
    if first.startswith("--constraint="):
        return _attached_constraint(tokens, first.split("=", 1)[1], line)
    if first.startswith("-c"):
        return _attached_constraint(tokens, first[2:], line)
    return None


def _separate_constraint(tokens: list[str], line: str) -> str:
    if len(tokens) != 2:
        raise ValueError(f"invalid constraint directive: {line}")
    return tokens[1]


def _attached_constraint(tokens: list[str], target: str, line: str) -> str:
    if len(tokens) != 1 or not target:
        raise ValueError(f"invalid constraint directive: {line}")
    return target


def _canonical_output(producer: str) -> str:
    if producer == "requirements-ci.in":
        return "requirements-ci.txt"
    return Path(producer).with_suffix(".lock").name


def _producer(name: str, target: str, inputs: dict[str, Path]) -> str:
    constraint = Path(target)
    if constraint.name != target or constraint.suffix not in (".lock", ".txt"):
        raise ValueError(f"{name}: unsupported constraint path {target!r}")
    producer = constraint.with_suffix(".in").name
    if producer not in inputs:
        raise ValueError(f"{name}: no generator for {target}")
    canonical = _canonical_output(producer)
    if target != canonical:
        raise ValueError(f"{name}: noncanonical generated constraint {target!r}; expected {canonical}")
    return producer


def _input_dependencies(name: str, path: Path, inputs: dict[str, Path]) -> set[str]:
    targets = (_constraint_target(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {_producer(name, target, inputs) for target in targets if target is not None}


def _dependencies(inputs: dict[str, Path]) -> dict[str, set[str]]:
    dependencies: dict[str, set[str]] = {}
    for name, path in sorted(inputs.items()):
        dependencies[name] = _input_dependencies(name, path, inputs)
    return dependencies


def _topological_order(dependencies: dict[str, set[str]]) -> list[str]:
    graph = {name: sorted(dependencies[name]) for name in sorted(dependencies)}
    try:
        return list(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        raise ValueError("constraint dependency cycle") from exc


def regeneration_order(root: Path) -> list[str]:
    """Fail closed on missing generators, nonlocal constraints, and cycles.

    Only root requirements-*.in / .lock pairs participate, except the canonical
    requirements-ci.in / requirements-ci.txt pair. All prerequisites
    are visited before their consumers, independent of alphabetical order.
    No resolver, network request, or repository-supplied program is executed.
    """
    inputs = {path.name: path for path in root.glob("requirements-*.in")}
    return _topological_order(_dependencies(inputs))

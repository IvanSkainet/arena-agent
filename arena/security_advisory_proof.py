"""Conservative numeric safe floor across every affected advisory release branch."""
from __future__ import annotations

import re
from typing import Any

from arena.security_manifest_proof import normalise, numeric_at_least, numeric_version

_RANGE = re.compile(r"(<=|>=|<|>|==|!=)\s*(\d+(?:\.\d+)*)")


def _past_upper_bound(operator: str, bound: str, patched: str) -> bool:
    if operator == "<":
        return numeric_at_least(patched, bound)
    if operator == "<=":
        return numeric_at_least(patched, bound) and not numeric_at_least(bound, patched)
    return False


def _range_bounds(affected: Any) -> list[tuple[str, str]] | None:
    if not isinstance(affected, str):
        return None
    bounds = []
    for part in affected.split(","):
        match = _RANGE.fullmatch(part.strip())
        if match is None:
            return None
        bounds.append((match[1], match[2]))
    return bounds


def _strictly_below(lower: str, upper: str) -> bool:
    return numeric_at_least(upper, lower) and not numeric_at_least(lower, upper)


def _bounds_for(bounds: list[tuple[str, str]], operators: tuple[str, ...]) -> list[str]:
    return [value for operator, value in bounds if operator in operators]


def _consistent_bounds(bounds: list[tuple[str, str]]) -> bool:
    upper = _bounds_for(bounds, ("<", "<="))
    lower = _bounds_for(bounds, (">", ">="))
    if (len(upper), len(lower), len(bounds)) not in ((1, 0, 1), (1, 1, 2)):
        return False
    return not lower or _strictly_below(lower[0], upper[0])


def _patched_version(vulnerability: dict[str, Any]) -> str | None:
    patched = vulnerability.get("first_patched_version")
    if not isinstance(patched, dict):
        return None
    version = patched.get("identifier")
    return version if _valid_numeric_version(version) else None


def _valid_numeric_version(value: Any) -> bool:
    return isinstance(value, str) and numeric_version(value) is not None


def _branch_floor(vulnerability: dict[str, Any]) -> str | None:
    version = _patched_version(vulnerability)
    if version is None:
        return None
    bounds = _range_bounds(vulnerability.get("vulnerable_version_range"))
    if bounds is None or not _consistent_bounds(bounds):
        return None
    escaped = any(_past_upper_bound(operator, bound, version) for operator, bound in bounds)
    return version if escaped else None


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_target(target: Any) -> bool:
    if not isinstance(target, dict):
        return False
    return all(_nonempty_string(target.get(key)) for key in ("name", "ecosystem"))


def _valid_vulnerability(value: Any) -> bool:
    return isinstance(value, dict) and _valid_target(value.get("package"))


def _matches_target(vulnerability: dict, package: str, ecosystem: str) -> bool:
    target = vulnerability["package"]
    return target["ecosystem"] == ecosystem and normalise(target["name"]) == normalise(package)


def _matching_branches(advisory: dict[str, Any], package: str, ecosystem: str) -> list[dict] | None:
    vulnerabilities = advisory.get("vulnerabilities")
    if not isinstance(vulnerabilities, list):
        return None
    if not all(_valid_vulnerability(value) for value in vulnerabilities):
        return None
    return [value for value in vulnerabilities if _matches_target(value, package, ecosystem)]


def _maximum_floor(floors: list[str | None]) -> str | None:
    if None in floors:
        return None
    return max((floor for floor in floors if floor is not None), key=lambda version: numeric_version(version) or ())


def advisory_floor(advisory: dict[str, Any], package: str, ecosystem: str) -> str | None:
    """No proof for missing/unbounded/unsupported branches; never use just one patch."""
    branches = _matching_branches(advisory, package, ecosystem)
    if not branches:
        return None
    floors = [_branch_floor(branch) for branch in branches]
    return _maximum_floor(floors)

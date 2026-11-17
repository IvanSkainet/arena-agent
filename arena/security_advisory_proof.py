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
    matches = [_RANGE.fullmatch(part.strip()) for part in affected.split(",")]
    if not matches or any(match is None for match in matches):
        return None
    return [(match[1], match[2]) for match in matches if match is not None]


def _strictly_below(lower: str, upper: str) -> bool:
    return numeric_at_least(upper, lower) and not numeric_at_least(lower, upper)


def _consistent_bounds(bounds: list[tuple[str, str]]) -> bool:
    upper = [value for operator, value in bounds if operator in ("<", "<=")]
    lower = [value for operator, value in bounds if operator in (">", ">=")]
    if len(upper) != 1 or len(lower) > 1 or len(upper) + len(lower) != len(bounds):
        return False
    return not lower or _strictly_below(lower[0], upper[0])


def _branch_floor(vulnerability: dict[str, Any]) -> str | None:
    patched = vulnerability.get("first_patched_version")
    version = patched.get("identifier") if isinstance(patched, dict) else None
    if not isinstance(version, str) or numeric_version(version) is None:
        return None
    bounds = _range_bounds(vulnerability.get("vulnerable_version_range"))
    if bounds is None or not _consistent_bounds(bounds):
        return None
    escaped = any(_past_upper_bound(operator, bound, version) for operator, bound in bounds)
    return version if escaped else None


def _valid_target(target: Any) -> bool:
    if not isinstance(target, dict):
        return False
    return all(isinstance(target.get(key), str) and bool(target[key].strip())
               for key in ("name", "ecosystem"))


def _matching_branches(advisory: dict[str, Any], package: str, ecosystem: str) -> list[dict] | None:
    vulnerabilities = advisory.get("vulnerabilities")
    if not isinstance(vulnerabilities, list):
        return None
    result = []
    for vulnerability in vulnerabilities:
        if not isinstance(vulnerability, dict):
            return None
        target = vulnerability.get("package", {})
        if not _valid_target(target):
            return None
        if target.get("ecosystem") == ecosystem and normalise(target["name"]) == normalise(package):
            result.append(vulnerability)
    return result


def advisory_floor(advisory: dict[str, Any], package: str, ecosystem: str) -> str | None:
    """No proof for missing/unbounded/unsupported branches; never use just one patch."""
    branches = _matching_branches(advisory, package, ecosystem)
    if not branches:
        return None
    floors = [_branch_floor(branch) for branch in branches]
    if any(floor is None for floor in floors):
        return None
    return max((floor for floor in floors if floor is not None), key=lambda version: numeric_version(version) or ())

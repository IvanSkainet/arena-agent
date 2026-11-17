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


def _branch_floor(vulnerability: dict[str, Any]) -> str | None:
    patched = vulnerability.get("first_patched_version") or {}
    version = patched.get("identifier") if isinstance(patched, dict) else None
    affected = vulnerability.get("vulnerable_version_range")
    if not isinstance(version, str) or numeric_version(version) is None:
        return None
    if not isinstance(affected, str):
        return None
    bounds = [_RANGE.fullmatch(part.strip()) for part in affected.split(",")]
    if not bounds or any(bound is None for bound in bounds):
        return None
    escaped = any(_past_upper_bound(bound[1], bound[2], version)
                  for bound in bounds if bound is not None)
    return version if escaped else None


def _matching_branches(advisory: dict[str, Any], package: str, ecosystem: str) -> list[dict] | None:
    vulnerabilities = advisory.get("vulnerabilities")
    if not isinstance(vulnerabilities, list):
        return None
    result = []
    for vulnerability in vulnerabilities:
        if not isinstance(vulnerability, dict):
            return None
        target = vulnerability.get("package", {})
        if not isinstance(target, dict):
            return None
        if target.get("ecosystem") == ecosystem and normalise(str(target.get("name", ""))) == normalise(package):
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

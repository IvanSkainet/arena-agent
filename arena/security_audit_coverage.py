"""Validate pip-audit inventory against its requested direct requirements."""
from __future__ import annotations

from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


def _parse_requirement(line: str) -> Requirement:
    try:
        requirement = Requirement(line)
    except InvalidRequirement as exc:
        raise ValueError("unsupported audit requirement syntax") from exc
    if requirement.url:
        raise ValueError("URL requirements cannot establish audit coverage")
    return requirement


def _requirements(text: str) -> list[Requirement]:
    requirements = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            requirements.append(_parse_requirement(line))
    if not requirements:
        raise ValueError("audit requirements must not be empty")
    return requirements


def _dependency_name(dependency: dict) -> str:
    name = dependency.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("audit inventory has a missing dependency name")
    if "skip_reason" in dependency:
        raise ValueError("audit inventory contains an unaudited dependency")
    return canonicalize_name(name, validate=True)


def _dependency_version(dependency: dict) -> Version:
    try:
        return Version(dependency["version"])
    except (KeyError, TypeError, InvalidVersion) as exc:
        raise ValueError("audit inventory has an invalid dependency version") from exc


def _inventory(dependencies: list[dict]) -> dict[str, Version]:
    inventory: dict[str, Version] = {}
    for dependency in dependencies:
        key = _dependency_name(dependency)
        if key in inventory:
            raise ValueError("audit inventory contains duplicate dependency names")
        inventory[key] = _dependency_version(dependency)
    return inventory


def _is_active(requirement: Requirement, environment: dict[str, str] | None) -> bool:
    return requirement.marker is None or requirement.marker.evaluate(environment=environment)


def _check_requirement(requirement: Requirement, inventory: dict[str, Version]) -> None:
    name = canonicalize_name(requirement.name)
    version = inventory.get(name)
    if version is None:
        raise ValueError(f"audit inventory is missing requested dependency: {name}")
    # Validate the version already resolved by pip, not pip's candidate-choice
    # policy. Prereleases still must satisfy every requested comparison.
    if not requirement.specifier.contains(version, prereleases=True):
        raise ValueError(f"audited version of {name} does not satisfy {requirement.specifier}")


def check_coverage(dependencies: list[dict], requirements_text: str,
                   environment: dict[str, str] | None = None) -> None:
    """Reject partial/stale audits; markers describe the scanner environment."""
    requirements = _requirements(requirements_text)
    inventory = _inventory(dependencies)
    for requirement in requirements:
        if _is_active(requirement, environment):
            _check_requirement(requirement, inventory)


def _validate_dependency(dependency: Any) -> None:
    if not isinstance(dependency, dict):
        raise ValueError("pip-audit dependency must be an object")
    fields = (dependency.get("name"), dependency.get("version"))
    if not all(isinstance(value, str) for value in fields):
        raise ValueError("pip-audit dependency has invalid name/version fields")
    vulns = dependency.get("vulns")
    if not isinstance(vulns, list) or any(not isinstance(vuln, dict) for vuln in vulns):
        raise ValueError("pip-audit dependency has invalid vulnerabilities")


def report_dependencies(report: dict) -> list[dict]:
    """Require a well-formed inventory even when the scanner exits zero."""
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("pip-audit report must contain a dependencies array")
    for dependency in dependencies:
        _validate_dependency(dependency)
    return dependencies


def finding_lines(dependencies: list[dict]) -> list[str]:
    """Render validated findings without changing the CVE blocking policy."""
    return [f"FAIL: CVE in {dep['name']}=={dep['version']}: "
            f"{vuln.get('id')} -- fix: {vuln.get('fix_versions')}"
            for dep in dependencies for vuln in dep["vulns"]]

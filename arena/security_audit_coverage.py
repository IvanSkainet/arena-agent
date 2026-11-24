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


# A constraint narrows the versions pip may choose and asks for no package, so
# there is nothing for the inventory to cover. Only this exact form is accepted;
# every other option line is still rejected by _parse_requirement.
CONSTRAINT_FLAGS = ("-c", "--constraint")


def _is_constraint(line: str) -> bool:
    tokens = line.split()
    return len(tokens) == 2 and tokens[0] in CONSTRAINT_FLAGS


def _content_lines(text: str) -> list[str]:
    lines = [raw.strip() for raw in text.splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def _requirements(text: str) -> list[Requirement]:
    requirements = [_parse_requirement(line) for line in _content_lines(text) if not _is_constraint(line)]
    if not requirements:
        raise ValueError("audit requirements must not be empty")
    return requirements


def _dependency_name(dependency: dict) -> str:
    name = _nonempty_text(dependency.get("name"))
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


def _as_object(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("pip-audit dependency/finding must be an object")
    return value


def _object_array(value: Any, label: str) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError(f"pip-audit report must contain a {label} array")
    return [_as_object(item) for item in value]


def _nonempty_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("audit inventory has a missing name/version field")
    return value


def _validate_dependency(dependency: dict) -> None:
    for field in ("name", "version"):
        _nonempty_text(dependency.get(field))
    _object_array(dependency.get("vulns"), "vulnerabilities")


def report_dependencies(report: dict) -> list[dict]:
    """Require a well-formed inventory even when the scanner exits zero."""
    dependencies = _object_array(report.get("dependencies"), "dependencies")
    for dependency in dependencies:
        _validate_dependency(dependency)
    return dependencies


def finding_lines(dependencies: list[dict]) -> list[str]:
    """Render validated findings without changing the CVE blocking policy."""
    return ["FAIL: CVE in {}=={}: {} -- fix: {}".format(
        dep["name"], dep["version"], vuln.get("id"), vuln.get("fix_versions"))
        for dep in dependencies for vuln in dep["vulns"]]

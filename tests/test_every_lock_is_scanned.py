"""Every hash-locked requirements file is read by the vulnerability scanner (#580)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

try:  # 3.11+ ships it; the 3.10 matrix cell installs tomli instead
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only on Python 3.10
    import tomli as tomllib

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
CONFIG = REPO / "osv-scanner.toml"
SECURITY_LOCK = "requirements-security.lock"
# An acceptance is looked at again at least this often.
LONGEST_ACCEPTANCE = timedelta(days=100)


def osv_arguments() -> list[str]:
    """Return the arguments the workflow gives to osv-scanner."""
    jobs = yaml.safe_load((WORKFLOWS / "security-scan.yml").read_text(encoding="utf-8"))["jobs"]
    steps = [
        step for job in jobs.values() for step in job["steps"]
        if "osv-scanner-action" in str(step.get("uses", ""))
    ]
    assert len(steps) == 1
    return str(steps[0]["with"]["scan-args"]).split()


@pytest.fixture(name="config")
def _config() -> dict[str, Any]:
    """Return the parsed osv-scanner configuration."""
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def test_every_lock_file_is_given_to_the_scanner() -> None:
    """A lock file that is not listed is a lock file nobody scans."""
    locks = sorted(path.name for path in REPO.glob("requirements-*.lock"))
    assert len(locks) >= 7
    prefix = "--lockfile=requirements.txt:"
    given = sorted(arg[len(prefix):] for arg in osv_arguments() if arg.startswith(prefix))
    assert given == locks


def test_no_lock_file_is_given_in_a_form_the_scanner_cannot_read() -> None:
    """Every --lockfile argument says how the file is to be parsed."""
    listed = [arg for arg in osv_arguments() if arg.startswith("--lockfile")]
    assert all(arg.startswith("--lockfile=requirements.txt:requirements-") for arg in listed)


def test_the_scanner_still_walks_the_tree() -> None:
    """The listed files are an addition to the recursive scan, not a replacement."""
    arguments = osv_arguments()
    assert "--recursive" in arguments
    assert arguments[-1] == "."


def test_every_accepted_advisory_has_a_reason_and_an_end_date(config: dict[str, Any]) -> None:
    """An acceptance without a reason or without an end is a silent suppression."""
    entries = config["IgnoredVulns"]
    assert len({entry["id"] for entry in entries}) == len(entries)
    for entry in entries:
        assert re.fullmatch(r"GHSA(-[0-9a-z]{4}){3}", entry["id"]), entry
        assert len(entry["reason"]) >= 60, entry["id"]
        assert isinstance(entry["ignoreUntil"], datetime), entry["id"]


def test_no_acceptance_reaches_far_into_the_future(config: dict[str, Any]) -> None:
    """Each entry stops working soon enough to be looked at again."""
    latest = datetime.now(timezone.utc) + LONGEST_ACCEPTANCE
    ends = [entry["ignoreUntil"] for entry in config["IgnoredVulns"]]
    ends += [entry["effectiveUntil"] for entry in config["PackageOverrides"]]
    assert all(end <= latest for end in ends)


def test_a_whole_package_is_passed_only_on_the_line_that_is_never_installed(config: dict[str, Any]) -> None:
    """The one package-wide acceptance is the Python 3.10 line of filelock."""
    overrides = config["PackageOverrides"]
    assert [(entry["name"], entry["version"], entry["ecosystem"]) for entry in overrides] == [
        ("filelock", "4.1.0", "PyPI"),
    ]
    assert overrides[0]["vulnerability"] == {"ignore": True}
    assert len(overrides[0]["reason"]) >= 60
    lock = (REPO / SECURITY_LOCK).read_text(encoding="utf-8")
    assert "filelock==4.1.0 ; python_full_version < '3.11'" in lock


def jobs_that_install(lock: str) -> list[tuple[str, dict[str, Any]]]:
    """Return every workflow job whose steps mention the lock file."""
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        jobs = yaml.safe_load(path.read_text(encoding="utf-8")).get("jobs", {})
        found += [
            (f"{path.name}:{name}", job) for name, job in jobs.items()
            if any(lock in str(step.get("run", "")) for step in job.get("steps", []))
        ]
    return found


def test_the_security_lock_is_installed_only_where_the_fixed_filelock_is_taken() -> None:
    """The acceptance above holds while every install of the lock runs on Python 3.11 or newer."""
    jobs = jobs_that_install(SECURITY_LOCK)
    assert len(jobs) >= 3
    for name, job in jobs:
        versions = [
            str(step["with"]["python-version"]) for step in job["steps"]
            if "actions/setup-python" in str(step.get("uses", ""))
        ]
        assert len(versions) == 1, name
        assert tuple(int(part) for part in versions[0].split(".")) >= (3, 11), name

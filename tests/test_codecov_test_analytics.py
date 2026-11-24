"""CI sends the JUnit file of every test job to Codecov Test Analytics (#586)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
CODECOV = "codecov/codecov-action@"


@pytest.fixture(name="steps")
def _steps() -> list[dict[str, Any]]:
    """Return the steps of the test job in ci.yml."""
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    return workflow["jobs"]["test"]["steps"]


def named(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """Return the one step with this name."""
    found = [step for step in steps if step.get("name") == name]
    assert len(found) == 1, name
    return found[0]


def test_the_uploaded_file_is_the_file_pytest_writes(steps: list[dict[str, Any]]) -> None:
    """An upload of a file nobody writes succeeds and sends nothing."""
    written = re.search(r"--junitxml=(.+?\.xml)", named(steps, "Run tests")["run"])
    assert written
    upload = named(steps, "Upload test results to Codecov")["with"]
    assert upload["files"] == "./" + written.group(1)
    assert upload["report_type"] == "test_results"


def test_the_upload_cannot_pick_up_other_files(steps: list[dict[str, Any]]) -> None:
    """With search on, the uploader collects committed fixtures as if they were fresh reports."""
    assert named(steps, "Upload test results to Codecov")["with"]["disable_search"] is True


def test_the_file_carries_the_path_of_every_test(steps: list[dict[str, Any]]) -> None:
    """Codecov names a test by its file; only the legacy family writes it."""
    assert "-o junit_family=legacy" in named(steps, "Run tests")["run"]


def test_a_failed_test_run_is_still_uploaded(steps: list[dict[str, Any]]) -> None:
    """A step that only runs after success would send every result except the failures."""
    upload = named(steps, "Upload test results to Codecov")
    assert upload["if"] == "${{ !cancelled() }}"
    assert steps.index(upload) > steps.index(named(steps, "Run tests"))


def test_an_outage_of_codecov_cannot_fail_ci(steps: list[dict[str, Any]]) -> None:
    """Codecov is an outside service; its trouble must not look like ours."""
    assert named(steps, "Upload test results to Codecov")["with"]["fail_ci_if_error"] is False


def test_both_uploads_use_the_same_pinned_action(steps: list[dict[str, Any]]) -> None:
    """Two pins of one action would drift apart at the next update."""
    pins = {step["uses"] for step in steps if str(step.get("uses", "")).startswith(CODECOV)}
    assert len(pins) == 1
    assert re.fullmatch(r"[0-9a-f]{40}", pins.pop().split("@")[1])

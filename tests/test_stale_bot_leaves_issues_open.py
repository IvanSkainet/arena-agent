"""The stale bot closes abandoned pull requests and never touches an issue (#590)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
STALE = "actions/stale@"


@pytest.fixture(name="inputs")
def _inputs() -> dict[str, Any]:
    """Return the inputs of the one actions/stale step in stale.yml."""
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "stale.yml").read_text(encoding="utf-8"))
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    found = [step for step in steps if str(step.get("uses", "")).startswith(STALE)]
    assert len(found) == 1, "stale.yml is expected to run actions/stale exactly once"
    return found[0]["with"]


# actions/stale reads a negative number as "never". 0 would mean "at once",
# and a missing input falls back to `days-before-stale` / `days-before-close`,
# whose defaults are 60 and 7 days.
@pytest.mark.parametrize("name", ["days-before-issue-stale", "days-before-issue-close"])
def test_an_issue_is_never_marked_and_never_closed(inputs: dict[str, Any], name: str) -> None:
    """An issue is a record of a defect; silence for 60 days does not make it false."""
    assert name in inputs, f"{name} is missing, so the action falls back to its default and acts on issues"
    assert int(inputs[name]) < 0, f"{name} is {inputs[name]!r}; only a negative number turns it off"


@pytest.mark.parametrize("name", ["days-before-stale", "days-before-close"])
def test_no_shared_input_brings_issues_back(inputs: dict[str, Any], name: str) -> None:
    """The shared inputs apply to issues and pull requests alike, so they stay unset."""
    assert name not in inputs, f"{name} applies to issues too; use the -pr- and -issue- inputs"


@pytest.mark.parametrize("name", ["days-before-pr-stale", "days-before-pr-close"])
def test_abandoned_pull_requests_are_still_closed(inputs: dict[str, Any], name: str) -> None:
    """Turning the bot off for issues must not turn it off for pull requests."""
    assert int(inputs[name]) > 0, f"{name} is {inputs[name]!r}; pull requests would no longer be closed"


def test_only_issues_is_not_set(inputs: dict[str, Any]) -> None:
    """With only: issues the pull-request policy above would silently stop."""
    assert inputs.get("only") in (None, "pulls"), inputs.get("only")

"""The CI test step runs in parallel without dropping what keeps a run honest."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
yaml = pytest.importorskip("yaml")


def _test_step() -> str:
    """Return the shell text of the `Run tests` step of the matrix job."""
    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["test"]
    (step,) = [step for step in job["steps"] if step.get("name") == "Run tests"]
    return step["run"]


def test_every_runner_gets_a_measured_worker_count() -> None:
    """Linux, macOS and the fallback each name a number; nothing is left to `auto`."""
    run = _test_step()
    assert dict(re.findall(r"^\s*(Linux|macOS|\*)\) WORKERS=(\d+) ;;$", run, re.M)) == {
        "Linux": "4", "macOS": "3", "*": "2"}
    assert '-n "$WORKERS" --max-worker-restart=0' in run


def test_the_parallel_step_keeps_the_guard_and_the_coverage_floor() -> None:
    """Workers change how long the run takes, not what it has to prove."""
    run = _test_step()
    assert "ARENA_TEST_EXECUTION_GUARD=1 pytest" in run
    assert "-p arena.governance.pytest_execution_guard" in run
    assert "--cov-fail-under=$THRESHOLD" in run
    assert re.findall(r"^\s*THRESHOLD=(\d+)$", run, re.M) == ["46", "51"]
    assert "--strict-markers" in run
    assert "no:randomly" not in run and "--no-cov" not in run

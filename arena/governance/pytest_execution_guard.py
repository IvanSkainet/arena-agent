"""Fail-closed pytest collection floor for the blocking OS/Python matrix."""
from __future__ import annotations

import os
from typing import Any

import pytest


def collection_floors() -> dict[str, int]:
    """Measured after the subagent listing fix (#57) on Linux; Windows keeps +5."""
    return {"Linux": 8808, "macOS": 8808, "Windows": 8813}


def collection_error(*, collected: int, runner_os: str) -> str | None:
    """Return the exact CI error when a platform collects too few tests."""
    minimum = collection_floors().get(runner_os)
    if minimum is None:
        return f"unknown RUNNER_OS for test collection guard: {runner_os or '<empty>'}"
    if collected < minimum:
        return (
            f"test collection floor failed on {runner_os}: "
            f"collected {collected}, required at least {minimum}"
        )
    return None


def pytest_collection_finish(session: Any) -> None:
    """Enforce only when the blocking CI test job opts into the plugin."""
    if os.environ.get("ARENA_TEST_EXECUTION_GUARD") != "1":
        return
    error = collection_error(
        collected=len(session.items),
        runner_os=os.environ.get("RUNNER_OS", ""),
    )
    if error:
        raise pytest.UsageError(error)

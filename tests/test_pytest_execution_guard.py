"""T65: the blocking matrix must fail when test modules disappear."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from arena.governance import pytest_execution_guard as guard


def test_measured_collection_floors_are_exact() -> None:
    assert guard.collection_floors() == {
        "Linux": 8754,
        "macOS": 8754,
        "Windows": 8759,
    }


@pytest.mark.parametrize(
    ("runner_os", "minimum"),
    sorted(guard.collection_floors().items()),
)
def test_collection_floor_accepts_exact_or_higher_count(
    runner_os: str, minimum: int
) -> None:
    assert guard.collection_error(
        collected=minimum, runner_os=runner_os
    ) is None
    assert guard.collection_error(
        collected=minimum + 1, runner_os=runner_os
    ) is None


@pytest.mark.parametrize(
    ("runner_os", "minimum"),
    sorted(guard.collection_floors().items()),
)
def test_collection_floor_rejects_one_missing_test(
    runner_os: str, minimum: int
) -> None:
    assert guard.collection_error(
        collected=minimum - 1, runner_os=runner_os
    ) == (
        f"test collection floor failed on {runner_os}: "
        f"collected {minimum - 1}, required at least {minimum}"
    )


@pytest.mark.parametrize("runner_os", ["", "FreeBSD", "linux"])
def test_unknown_runner_is_rejected(runner_os: str) -> None:
    rendered = runner_os or "<empty>"
    assert guard.collection_error(
        collected=100_000, runner_os=runner_os
    ) == f"unknown RUNNER_OS for test collection guard: {rendered}"


def test_pytest_hook_is_disabled_without_explicit_ci_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("ARENA_TEST_EXECUTION_GUARD", raising=False)
    guard.pytest_collection_finish(SimpleNamespace(items=[]))


def test_pytest_hook_rejects_missing_runner_identity(monkeypatch) -> None:
    monkeypatch.setenv("ARENA_TEST_EXECUTION_GUARD", "1")
    monkeypatch.delenv("RUNNER_OS", raising=False)
    with pytest.raises(pytest.UsageError) as caught:
        guard.pytest_collection_finish(SimpleNamespace(items=[]))
    assert str(caught.value) == (
        "unknown RUNNER_OS for test collection guard: <empty>"
    )


def test_pytest_hook_uses_runner_specific_floor(monkeypatch) -> None:
    monkeypatch.setenv("ARENA_TEST_EXECUTION_GUARD", "1")
    monkeypatch.setenv("RUNNER_OS", "Windows")
    minimum = guard.collection_floors()["Windows"]
    session = SimpleNamespace(items=[object()] * minimum)
    guard.pytest_collection_finish(session)
    session.items.pop()
    with pytest.raises(pytest.UsageError) as caught:
        guard.pytest_collection_finish(session)
    assert str(caught.value) == (
        f"test collection floor failed on Windows: collected {minimum - 1}, "
        f"required at least {minimum}"
    )

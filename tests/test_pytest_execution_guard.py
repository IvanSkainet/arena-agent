"""T65: the blocking matrix must fail when test modules disappear."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from arena.governance import pytest_execution_guard as guard


def test_measured_collection_floors_are_exact() -> None:
    assert guard.collection_floors() == {
        "Linux": 9195,
        "macOS": 9195,
        "Windows": 9200,
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


def test_parallel_controller_rejects_short_worker_collection(monkeypatch):
    monkeypatch.setenv("ARENA_TEST_EXECUTION_GUARD", "1")
    monkeypatch.setenv("RUNNER_OS", "Linux")
    with pytest.raises(pytest.exit.Exception, match="test collection floor failed") as caught:
        guard.pytest_xdist_node_collection_finished(node=None, ids=["one"])
    assert caught.value.returncode == 4


def test_parallel_controller_accepts_complete_worker_collection(monkeypatch):
    monkeypatch.setenv("ARENA_TEST_EXECUTION_GUARD", "1")
    monkeypatch.setenv("RUNNER_OS", "Linux")
    guard.pytest_xdist_node_collection_finished(
        node=None, ids=["test"] * guard.collection_floors()["Linux"])


def test_parallel_controller_is_disabled_without_opt_in(monkeypatch):
    monkeypatch.delenv("ARENA_TEST_EXECUTION_GUARD", raising=False)
    guard.pytest_xdist_node_collection_finished(node=None, ids=[])


def test_parallel_worker_defers_floor_to_controller(monkeypatch):
    monkeypatch.setenv("ARENA_TEST_EXECUTION_GUARD", "1")
    guard.pytest_collection_finish(
        SimpleNamespace(items=[], config=SimpleNamespace(workerinput={})))


def test_parallel_controller_rejects_missing_runner_identity(monkeypatch):
    monkeypatch.setenv("ARENA_TEST_EXECUTION_GUARD", "1")
    monkeypatch.delenv("RUNNER_OS", raising=False)
    with pytest.raises(pytest.exit.Exception) as caught:
        guard.pytest_xdist_node_collection_finished(node=None, ids=[])
    assert str(caught.value) == "unknown RUNNER_OS for test collection guard: <empty>"
    assert caught.value.returncode == 4


def test_parallel_hook_registers_without_xdist_hookspec():
    # A serial-only plugin manager must accept this optional xdist hook.
    # Real subprocess verdict contracts separately exercise xdist registration.
    manager = pytest.PytestPluginManager()
    manager.register(guard)
    manager.check_pending()

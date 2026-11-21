"""T74: real subprocess contracts for serial and parallel pytest verdicts."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = ("healthy", "under-collected", "assertion", "worker-crash",
         "environment-leak", "coverage-failure")


def _source(case: str) -> str:
    first = "def test_one():\n    assert True\n"
    second = {
        "healthy": "assert True",
        "assertion": "assert False",
        "worker-crash": "import os; os._exit(23)",
        "environment-leak": 'import os; os.environ["ARENA_CONTRACT_LEAK"] = "fixture-value"',
        "coverage-failure": "import contract_target; assert contract_target.used() == 1",
    }
    if case == "under-collected":
        return first
    return first + f"\ndef test_two():\n    {second[case]}\n"


def _run(tmp_path: Path, *, case: str, workers: int) -> subprocess.CompletedProcess[str]:
    # A private project/config prevents inheriting addopts or writing coverage
    # reports into the source checkout. No optional import/skip: CI locks xdist.
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    conftest = (
        "from arena.governance import pytest_execution_guard as guard\n"
        'guard.collection_floors = lambda: {"Linux": 2}\n'
    )
    if case == "mismatched-collection":
        conftest = conftest.replace('"Linux": 2', '"Linux": 1') + (
            "def pytest_collection_modifyitems(config, items):\n"
            '    if getattr(config, "workerinput", {}).get("workerid") == "gw1":\n'
            "        items.pop()\n"
        )
    (tmp_path / "conftest.py").write_text(conftest, encoding="utf-8")
    source_case = "healthy" if case == "mismatched-collection" else case
    (tmp_path / "test_contract.py").write_text(_source(source_case), encoding="utf-8")
    command = [sys.executable, "-m", "pytest", "-q", "-c", str(config),
               "-p", "no:randomly", "-p", "arena.governance.pytest_execution_guard"]
    if workers:
        command += ["-n", str(workers), "--max-worker-restart=0"]
    else:
        command += ["-p", "no:xdist"]
    if case == "environment-leak":
        command += ["-p", "tests.conftest"]
    if case == "coverage-failure":
        (tmp_path / "contract_target.py").write_text(
            "def used():\n    return 1\ndef unused():\n    return 2\n", encoding="utf-8")
        command += ["--cov=contract_target", "--cov-fail-under=100", "--cov-report=term"]
    else:
        command += ["--no-cov"]
    env = dict(os.environ, ARENA_TEST_EXECUTION_GUARD="1", RUNNER_OS="Linux", PYTHONPATH=str(ROOT))
    for control in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD"):
        env.pop(control, None)
    if sys.platform != "linux":
        return subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=60)
    from arena.governance.benchmark_runner import execute

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
        status = execute(command, root=tmp_path, env=env, log=log, timeout=60)
        log.seek(0)
        return subprocess.CompletedProcess(command, status, log.read(), "")


@pytest.mark.parametrize("workers", [0, 2])
@pytest.mark.parametrize("case", CASES)
def test_real_pytest_verdicts(tmp_path, case, workers):
    result = _run(tmp_path, case=case, workers=workers)
    output = result.stdout + result.stderr
    if case == "healthy":
        assert result.returncode == 0, output
        assert "2 passed" in output
    elif case == "under-collected":
        assert result.returncode == 4, output
        assert "test collection floor failed" in output
    elif case == "worker-crash":
        assert result.returncode != 0, output
    else:
        assert result.returncode == 1, output
        expected = {
            "assertion": "1 failed",
            "environment-leak": "environment leaked",
            "coverage-failure": "FAIL Required test coverage of 100% not reached",
        }
        assert expected[case] in output


def test_mismatched_worker_collection_is_rejected(tmp_path):
    result = _run(tmp_path, case="mismatched-collection", workers=2)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Different tests were collected" in result.stdout + result.stderr


@pytest.mark.parametrize("control,value", [
    ("PYTEST_ADDOPTS", "-k nonexistent_contract_case"),
    ("PYTEST_PLUGINS", "nonexistent_contract_plugin"),
    ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1"),
])
def test_verdict_contracts_ignore_parent_pytest_controls(tmp_path, monkeypatch, control, value):
    monkeypatch.setenv(control, value)
    result = _run(tmp_path, case="healthy", workers=0)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


def test_console_pytest_finds_shared_helpers_without_pythonpath(tmp_path):
    import shutil

    executable = shutil.which("pytest")
    assert executable is not None
    env = dict(os.environ)
    for control in ("PYTHONPATH", "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD"):
        env.pop(control, None)
    result = subprocess.run(
        [executable, "-o", "addopts=", "--no-cov", "--collect-only", "-q", str(ROOT / "tests/test_benchmark_reports.py")],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_junit_durations_must_be_finite_and_nonnegative" in result.stdout

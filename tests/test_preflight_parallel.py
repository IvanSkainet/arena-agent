"""T74: local parallel opt-in must preserve gates and propagate failures."""
from types import SimpleNamespace

import pytest

from scripts import preflight


@pytest.fixture(name="harness")
def preflight_harness(monkeypatch):
    checks = [preflight.Check("fast guard", ["guard"]),
              preflight.Check("full suite", [preflight.PY, "-m", "pytest", "--no-cov"], slow=True)]
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(preflight, "CHECKS", checks)
    monkeypatch.setattr(preflight, "platform", SimpleNamespace(system=lambda: "Linux"))
    monkeypatch.setattr(preflight, "subprocess", SimpleNamespace(run=run))
    monkeypatch.setattr(preflight, "_execute_full", lambda argv, env: preflight.subprocess.run(argv, env=env))
    return calls


def test_full_remains_serial_by_default(harness):
    assert preflight.main(["--full"]) == 0
    assert harness == [["guard"], [preflight.PY, "-m", "pytest", "--no-cov",
                                     "-p", "arena.governance.pytest_execution_guard"]]


def test_parallel_opt_in_preserves_fast_guard_and_suite_options(harness):
    assert preflight.main(["--full", "--workers", "2"]) == 0
    assert harness == [["guard"], [preflight.PY, "-m", "pytest", "--no-cov",
                                    "-p", "arena.governance.pytest_execution_guard", "-n", "2", "--max-worker-restart=0"]]
    assert preflight.CHECKS[-1].argv == [preflight.PY, "-m", "pytest", "--no-cov"]


def test_parallel_failure_is_not_reported_as_success(harness, monkeypatch):
    def run(argv, **kwargs):
        harness.append(argv)
        return SimpleNamespace(returncode=1 if "-n" in argv else 0, stdout="failed", stderr="")

    monkeypatch.setattr(preflight, "subprocess", SimpleNamespace(run=run))
    assert preflight.main(["--full", "--workers", "2"]) == 1
    assert harness[0] == ["guard"]
    assert "-n" in harness[1]
    assert len(harness) == 2


@pytest.mark.parametrize("args", [["--workers", "2"], ["--full", "--workers", "4"]])
def test_invalid_parallel_requests_fail_before_running_checks(harness, args):
    with pytest.raises(SystemExit) as caught:
        preflight.main(args)
    assert caught.value.code == 2
    assert harness == []


@pytest.mark.parametrize("system", ["Windows", "Darwin"])
def test_unmeasured_platforms_keep_serial_mode(harness, monkeypatch, system):
    monkeypatch.setattr(preflight, "platform", SimpleNamespace(system=lambda: system))
    with pytest.raises(SystemExit) as caught:
        preflight.main(["--full", "--workers", "2"])
    assert caught.value.code == 2
    assert harness == []
    assert preflight.main(["--full"]) == 0


def test_list_exposes_actual_parallel_command_without_execution(harness, capsys):
    assert preflight.main(["--full", "--workers", "2", "--list"]) == 0
    assert "-n 2 --max-worker-restart=0" in capsys.readouterr().out
    assert harness == []


def test_fast_default_does_not_run_full_suite(harness):
    assert preflight.main([]) == 0
    assert harness == [["guard"]]


def test_parallel_missing_tool_is_a_failure(harness, monkeypatch):
    monkeypatch.setattr(preflight.CHECKS[0], "needs", "fixture-absent-tool")
    monkeypatch.setattr(preflight, "shutil", SimpleNamespace(which=lambda name: None))
    assert preflight.main(["--full", "--workers", "2"]) == 1
    assert harness == [[preflight.PY, "-m", "pytest", "--no-cov",
                        "-p", "arena.governance.pytest_execution_guard", "-n", "2", "--max-worker-restart=0"]]


@pytest.mark.parametrize("system,runner", [("Linux", "Linux"), ("Darwin", "macOS"), ("Windows", "Windows")])
def test_full_suite_arms_collection_guard_without_mutating_parent(harness, monkeypatch, system, runner):
    import os

    monkeypatch.setattr(preflight, "platform", SimpleNamespace(system=lambda: system))
    monkeypatch.setenv("ARENA_TEST_EXECUTION_GUARD", "0")
    environments = []

    def run(argv, **kwargs):
        if "pytest" in argv:
            environments.append(kwargs["env"])
            assert "arena.governance.pytest_execution_guard" in argv
        else:
            assert kwargs["env"] is None
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(preflight, "subprocess", SimpleNamespace(run=run))
    assert preflight.main(["--full"]) == 0
    assert environments[0]["ARENA_TEST_EXECUTION_GUARD"] == "1"
    assert environments[0]["RUNNER_OS"] == runner
    assert os.environ["ARENA_TEST_EXECUTION_GUARD"] == "0"


@pytest.mark.parametrize("workers", [1, 2])
def test_real_preflight_rejects_truncated_full_suite(tmp_path, workers, capsys):
    import platform
    import sys

    if workers == 2 and platform.system() != "Linux":
        pytest.skip("two-worker preflight is Linux-only")
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    test_file = tmp_path / "test_too_short.py"
    test_file.write_text("def test_one():\n    assert True\n", encoding="utf-8")
    check = preflight.Check("full suite", [sys.executable, "-m", "pytest", "--no-cov",
                                         "-p", "no:randomly", "-c", str(config), str(test_file),
                                         "--timeout=10"], slow=True)
    assert preflight._run_check(check, workers) == "full suite"
    assert "test collection floor failed" in capsys.readouterr().out


@pytest.mark.skipif(__import__("sys").platform != "linux", reason="Linux owned process-group preflight")
def test_linux_full_suite_delegates_to_owned_lifecycle(monkeypatch):
    from arena.governance import benchmark_runner

    calls = []

    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        kwargs["log"].write("fixture output\n")
        return 4

    monkeypatch.setattr(benchmark_runner, "execute", execute)
    result = preflight._execute_full(["fixture"], {"RUNNER_OS": "Linux"})
    assert result.returncode == 4
    assert result.stdout == "fixture output\n"
    assert calls[0][1]["timeout"] is None
    assert calls[0][1]["env"] == {"RUNNER_OS": "Linux"}
    assert calls[0][1]["root"] == preflight.ROOT

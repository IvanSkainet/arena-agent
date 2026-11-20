"""T74: local parallel opt-in must preserve gates and propagate failures."""
from types import SimpleNamespace

import pytest

from scripts import preflight


@pytest.fixture
def harness(monkeypatch):
    checks = [preflight.Check("fast guard", ["guard"]),
              preflight.Check("full suite", [preflight.PY, "-m", "pytest", "--no-cov"], slow=True)]
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(preflight, "CHECKS", checks)
    monkeypatch.setattr(preflight, "platform", SimpleNamespace(system=lambda: "Linux"))
    monkeypatch.setattr(preflight, "subprocess", SimpleNamespace(run=run))
    return calls


def test_full_remains_serial_by_default(harness):
    assert preflight.main(["--full"]) == 0
    assert harness == [["guard"], [preflight.PY, "-m", "pytest", "--no-cov"]]


def test_parallel_opt_in_preserves_fast_guard_and_suite_options(harness):
    assert preflight.main(["--full", "--workers", "2"]) == 0
    assert harness == [["guard"], [preflight.PY, "-m", "pytest", "--no-cov",
                                    "-n", "2", "--max-worker-restart=0"]]
    assert preflight.CHECKS[-1].argv == [preflight.PY, "-m", "pytest", "--no-cov"]


def test_parallel_failure_is_not_reported_as_success(harness, monkeypatch):
    monkeypatch.setattr(preflight, "subprocess", SimpleNamespace(
        run=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="failed", stderr="")))
    assert preflight.main(["--full", "--workers", "2"]) == 1


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
                        "-n", "2", "--max-worker-restart=0"]]

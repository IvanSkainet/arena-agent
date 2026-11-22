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
    monkeypatch.setattr(preflight, "_usable_cpus", lambda: 4)
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


@pytest.mark.parametrize("args", [["--workers", "2"], ["--workers", "1"], ["--full", "--workers", "5"],
                                  ["--full", "--workers", "0"], ["--full", "--workers", "auto"]])
def test_invalid_parallel_requests_fail_before_running_checks(harness, args):
    with pytest.raises(SystemExit) as caught:
        preflight.main(args)
    assert caught.value.code == 2
    assert harness == []


@pytest.mark.parametrize("system", ["Linux", "Windows", "Darwin"])
@pytest.mark.parametrize("workers", [2, 3, 4])
def test_every_platform_accepts_the_measured_worker_counts(harness, monkeypatch, system, workers):
    monkeypatch.setattr(preflight, "platform", SimpleNamespace(system=lambda: system))
    assert preflight.main(["--full", "--workers", str(workers)]) == 0
    assert harness[-1][-3:] == ["-n", str(workers), "--max-worker-restart=0"]


@pytest.mark.parametrize("system", ["Windows", "Darwin"])
def test_outside_linux_the_suite_command_reaches_the_process_unchanged(monkeypatch, system):
    """The harness above replaces the executor; this one runs the real dispatch."""
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs["env"], kwargs["check"]))
        return SimpleNamespace(returncode=3, stdout="", stderr="")

    monkeypatch.setattr(preflight, "platform", SimpleNamespace(system=lambda: system))
    monkeypatch.setattr(preflight, "subprocess", SimpleNamespace(run=run))
    argv = [preflight.PY, "-m", "pytest", "-n", "2", "--max-worker-restart=0"]
    env = {"ARENA_TEST_EXECUTION_GUARD": "1"}
    assert preflight._execute_full(argv, env).returncode == 3
    assert seen == [(argv, env, False)]


@pytest.mark.parametrize("limit", [(2, 3), (3, 4), (1, 2)])
def test_more_workers_than_cpus_is_refused_before_running_checks(harness, monkeypatch, capsys, limit):
    cpus, workers = limit
    monkeypatch.setattr(preflight, "_usable_cpus", lambda: cpus)
    with pytest.raises(SystemExit) as caught:
        preflight.main(["--full", "--workers", str(workers)])
    assert caught.value.code == 2
    assert harness == []
    assert f"exceeds the {cpus} CPUs available" in capsys.readouterr().err


def test_as_many_workers_as_cpus_is_accepted(harness, monkeypatch):
    monkeypatch.setattr(preflight, "_usable_cpus", lambda: 2)
    assert preflight.main(["--full", "--workers", "2"]) == 0
    assert harness[-1][-3:] == ["-n", "2", "--max-worker-restart=0"]


def test_one_worker_is_never_refused_for_lack_of_cpus(harness, monkeypatch):
    monkeypatch.setattr(preflight, "_usable_cpus", lambda: 0)
    assert preflight.main(["--full"]) == 0
    assert harness == [["guard"], [preflight.PY, "-m", "pytest", "--no-cov",
                                     "-p", "arena.governance.pytest_execution_guard"]]


def test_usable_cpus_follows_the_affinity_mask_where_there_is_one(monkeypatch):
    monkeypatch.setattr(preflight.os, "sched_getaffinity", lambda pid: {0, 5}, raising=False)
    monkeypatch.setattr(preflight.os, "cpu_count", lambda: 64)
    assert preflight._usable_cpus() == 2
    monkeypatch.delattr(preflight.os, "sched_getaffinity")
    assert preflight._usable_cpus() == 64
    monkeypatch.setattr(preflight.os, "cpu_count", lambda: None)
    assert preflight._usable_cpus() == 1


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
    import sys

    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    test_file = tmp_path / "test_too_short.py"
    test_file.write_text("def test_one():\n    assert True\n", encoding="utf-8")
    check = preflight.Check("full suite", [sys.executable, "-m", "pytest", "--no-cov",
                                         "-p", "no:randomly", "-c", str(config), str(test_file)], slow=True)
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
    assert calls[0][1]["context"].env == {"RUNNER_OS": "Linux"}
    assert calls[0][1]["context"].root == preflight.ROOT


@pytest.mark.parametrize("workers", [1, 2])
def test_full_suite_neutralizes_inherited_selection_and_worker_options(harness, monkeypatch, workers):
    import os

    inherited = "-n auto --dist=loadscope -k truncated"
    monkeypatch.setenv("PYTEST_ADDOPTS", inherited)
    environments = []

    def run(argv, **kwargs):
        environments.append((argv, kwargs.get("env")))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(preflight, "subprocess", SimpleNamespace(run=run))
    assert preflight.main(["--full", "--workers", str(workers)]) == 0
    assert environments[0][1] is None  # Fast checks retain the parent's environment.
    assert "PYTEST_ADDOPTS" not in environments[1][1]
    assert os.environ["PYTEST_ADDOPTS"] == inherited


@pytest.mark.skipif(__import__("sys").platform != "linux", reason="Linux owned SIGTERM cleanup")
@pytest.mark.parametrize("interrupted", [False, True])
def test_full_suite_installs_and_restores_sigterm_cancellation(monkeypatch, interrupted):
    import signal

    from arena.governance import benchmark_runner

    original = signal.getsignal(signal.SIGTERM)

    def sentinel(signum, frame):
        return None

    def execute(*args, **kwargs):
        assert signal.getsignal(signal.SIGTERM) == signal.default_int_handler
        if interrupted:
            raise KeyboardInterrupt
        return 0

    monkeypatch.setattr(benchmark_runner, "execute", execute)
    signal.signal(signal.SIGTERM, sentinel)
    try:
        if interrupted:
            with pytest.raises(KeyboardInterrupt):
                preflight._execute_full(["fixture"], {})
        else:
            assert preflight._execute_full(["fixture"], {}).returncode == 0
        assert signal.getsignal(signal.SIGTERM) is sentinel
    finally:
        signal.signal(signal.SIGTERM, original)


@pytest.mark.skipif(__import__("sys").platform != "linux", reason="Linux owned checkout entrypoint")
def test_script_full_executor_imports_checkout_without_editable_install(tmp_path):
    import subprocess
    import sys

    code = (
        "import pathlib,runpy,sys; "
        f"root=pathlib.Path({str(preflight.ROOT)!r}); "
        "sys.path[:]=[p for p in sys.path if pathlib.Path(p).resolve()!=root]; "
        "sys.meta_path[:]=[f for f in sys.meta_path if not getattr(f,'__module__','').startswith('__editable__')]; "
        f"module=runpy.run_path({str(preflight.ROOT / 'scripts/preflight.py')!r}); "
        "assert module['_execute_full']([sys.executable,'-c','pass'],{}).returncode==0"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path,
                            capture_output=True, text=True, check=False, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr

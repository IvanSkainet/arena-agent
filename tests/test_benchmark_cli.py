"""T74: explicit CLI validation and fixed pytest argument structure."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from arena.governance import benchmark_runner as bench
from tests._benchmark_support import invoke, measurement_fixture as measurement_fixture


def test_serial_command_has_no_parallel_flags(tmp_path):
    argv = bench.command("serial", 271, tmp_path, "Linux")
    assert argv[-2:] == ["-p", "no:xdist"]
    assert "-n" not in argv
    assert "--cov-fail-under=51" in argv
    parallel = bench.command("n2", 271, tmp_path, "Linux")
    assert parallel[-3:] == ["-n", "2", "--max-worker-restart=0"]



def test_unvalidated_platform_does_not_launch(measurement, monkeypatch):
    monkeypatch.setattr(bench.platform, "system", lambda: "Windows")
    with pytest.raises(ValueError, match="only on Linux"):
        invoke(measurement)
    assert measurement[3] == []



@pytest.mark.parametrize("args", [[], ["--mode", "auto"],
    ["--mode", "serial", "--seed", "17", "--output", "fixture", "--timeout", "0"]])
def test_invalid_cli_does_not_start_measurement(monkeypatch, args):
    def forbidden(*a, **kw):
        pytest.fail("invalid command launched a benchmark")

    monkeypatch.setattr(bench, "run", forbidden)
    with pytest.raises(SystemExit) as caught:
        bench.main(args)
    assert caught.value.code == 2



def test_cli_installs_and_restores_interrupt_handlers(monkeypatch, tmp_path):
    before = {sig: bench.signal.getsignal(sig) for sig in (bench.signal.SIGINT, bench.signal.SIGTERM)}

    def run(*args, **kwargs):
        for sig in before:
            assert bench.signal.getsignal(sig) == bench.signal.default_int_handler
        return 0

    monkeypatch.setattr(bench, "run", run)
    assert bench.main(["--mode", "serial", "--seed", "17", "--output", str(tmp_path)]) == 0
    assert {sig: bench.signal.getsignal(sig) for sig in before} == before



def test_default_root_is_the_repository_not_its_parent():
    assert bench.ROOT == Path(__file__).resolve().parents[1]



@pytest.mark.parametrize("mode,timeout", [("auto", 60), ("serial", 0), ("n2", -1)])
def test_api_rejects_invalid_mode_or_timeout_without_starting(measurement, mode, timeout):
    with pytest.raises(ValueError, match="^invalid mode or timeout$"):
        bench.run(measurement[0], measurement[1], mode=mode, seed=17, timeout=timeout)
    assert measurement[3] == []



def test_command_preserves_every_gate_and_explicit_report_path(tmp_path):
    for runner, floor in [("Linux", 51), ("macOS", 46)]:
        assert bench.command("n2", 17, tmp_path, runner) == [
            sys.executable, "-m", "pytest", "-q", "-p", "arena.governance.pytest_execution_guard",
            "--randomly-seed=17", f"--cov-fail-under={floor}",
            f"--junitxml={tmp_path / 'junit.xml'}", "--cov-report=term",
            f"--cov-report=xml:{tmp_path / 'coverage.xml'}", f"--cov-config={tmp_path / 'coverage.toml'}",
            "-n", "2", "--max-worker-restart=0",
        ]



@pytest.mark.parametrize("args", [
    ["--seed", "17", "--output", "fixture"],
    ["--mode", "serial", "--output", "fixture"],
    ["--mode", "serial", "--seed", "17"],
])
def test_each_required_cli_argument_is_independently_enforced(monkeypatch, args):
    monkeypatch.setattr(bench, "run", lambda *a, **kw: pytest.fail("missing argument reached engine"))
    with pytest.raises(SystemExit) as caught:
        bench.main(args)
    assert caught.value.code == 2



@pytest.mark.parametrize("timeout", [None, 1])
def test_parallel_cli_passes_valid_parameters_and_default_budget(monkeypatch, tmp_path, timeout):
    def run(root, output, **kwargs):
        assert root == bench.ROOT
        assert output == tmp_path
        assert kwargs == {"mode": "n2", "seed": 271, "timeout": 1800 if timeout is None else timeout}
        return 0

    monkeypatch.setattr(bench, "run", run)
    args = ["--mode", "n2", "--seed", "271", "--output", str(tmp_path)]
    if timeout is not None:
        args += ["--timeout", str(timeout)]
    assert bench.main(args) == 0



@pytest.mark.parametrize("failure", ["budget", "startup"])
def test_cli_reports_why_it_refused_the_measurement(monkeypatch, tmp_path, capsys, failure):
    def run(*a, **kw):
        raise ValueError("fixture")

    monkeypatch.setattr(bench, "run", run)
    args = ["--mode", "serial", "--seed", "17", "--output", str(tmp_path)]
    if failure == "budget":
        args += ["--timeout", "0"]
    with pytest.raises(SystemExit) as caught:
        bench.main(args)
    assert caught.value.code == 2
    diagnostic = "timeout must be positive" if failure == "budget" else "cannot start measurement: ValueError"
    assert capsys.readouterr().err.splitlines()[-1].endswith(": error: " + diagnostic)



@pytest.mark.parametrize("seed", ["17 --override-ini=addopts=-x", "17;touch marker", "$(touch marker)", "--help"])
def test_cli_rejects_injected_seed_before_starting_a_process(monkeypatch, tmp_path, seed):
    def forbidden(*args, **kwargs):
        pytest.fail("unparsed seed reached measurement")

    monkeypatch.setattr(bench, "run", forbidden)
    with pytest.raises(SystemExit) as caught:
        bench.main(["--mode", "serial", "--seed=" + seed, "--output", str(tmp_path)])
    assert caught.value.code == 2



def test_output_option_metacharacters_remain_one_literal_argument(tmp_path):
    output = tmp_path / "report --override-ini=addopts=-x;$(touch marker)"
    argv = bench.command("serial", 17, output, "Linux")
    assert f"--junitxml={output / 'junit.xml'}" in argv
    assert "--override-ini=addopts=-x" not in argv
    assert "--randomly-seed=17" in argv

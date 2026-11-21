"""T74: complete measurement verdicts and startup/failure records."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from arena.governance import benchmark_runner as bench
from tests._benchmark_support import invoke, measurement_fixture as measurement_fixture, report


def test_complete_measurement_preserves_command_outcomes_and_private_paths(measurement):
    assert invoke(measurement) == 0
    result = report(measurement)
    assert result["state"] == "passed"
    assert result["source_unchanged"] is True
    assert result["junit"]["count"] == 2
    assert result["junit"]["cases"][1]["reason"] == "fixture reason"
    assert result["command"][-3:] == ["-n", "2", "--max-worker-restart=0"]
    assert "--cov-fail-under=51" in result["command"]
    env = measurement[3][0][1]["context"].env
    assert env["ARENA_TEST_EXECUTION_GUARD"] == "1"
    assert env["RUNNER_OS"] == "Linux"
    assert "COVERAGE_FILE" not in env
    assert f"--cov-config={measurement[1] / 'coverage.toml'}" in result["command"]
    assert not Path(env["HOME"]).exists()  # private scratch cleaned up
    assert result["peak_memory_bytes"] is None
    assert "env" not in result



@pytest.mark.parametrize("code", [1, 2, 3, 4, 5, -9])
def test_failed_pytest_is_never_successful(measurement, monkeypatch, code):
    healthy = bench.execute

    def execute(*args, **kwargs):
        healthy(*args, **kwargs)
        return code

    monkeypatch.setattr(bench, "execute", execute)
    assert invoke(measurement) == (code if code >= 0 else 1)
    assert report(measurement)["state"] == "failed"



@pytest.mark.parametrize("error,code", [(subprocess.TimeoutExpired("pytest", 1), 124),
                                        (KeyboardInterrupt(), 130), (OSError(), 1)])
def test_interrupted_measurement_retains_failure_record(measurement, monkeypatch, error, code):
    def execute(*args, **kwargs):
        raise error

    monkeypatch.setattr(bench, "execute", execute)
    assert invoke(measurement) == code
    assert report(measurement)["exit"] == code
    assert report(measurement)["state"] == "failed"



def test_missing_coverage_is_a_failure_even_after_pytest_exit_zero(measurement, monkeypatch):
    def missing(path):
        raise ValueError("coverage missing")

    monkeypatch.setattr(bench, "read_coverage", missing)
    assert invoke(measurement) == 1
    assert report(measurement)["state"] == "failed"



def test_source_mutation_invalidates_otherwise_successful_run(measurement, monkeypatch):
    healthy = bench.execute

    def execute(*args, **kwargs):
        code = healthy(*args, **kwargs)
        measurement[2].write_text("changed")
        return code

    monkeypatch.setattr(bench, "execute", execute)
    assert invoke(measurement) == 1
    assert report(measurement)["source_unchanged"] is False



def test_coverage_destination_is_not_exported_to_nested_commands(measurement, monkeypatch):
    monkeypatch.setenv("COVERAGE_FILE", "/fixture/inherited-data-must-not-be-used")
    assert invoke(measurement) == 0
    from coverage import Coverage

    # Coverage's environment override applies when reading a config directly,
    # so mirror the sanitized environment passed to execute().
    monkeypatch.delenv("COVERAGE_FILE")
    config = Coverage(config_file=str(measurement[1] / "coverage.toml")).config
    assert config.data_file == str(measurement[1] / ".coverage")
    assert config.branch is True
    assert "COVERAGE_FILE" not in measurement[3][0][1]["context"].env



@pytest.mark.skipif(sys.platform != "linux", reason="Linux measurement integration")
def test_nested_statement_coverage_does_not_pollute_parent_branch_data(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "target.py").write_text("def used():\n    return 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[tool.coverage.run]\nbranch = true\nsource = ["target"]\n', encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (root / "test_parent.py").write_text(
        'import os, subprocess, sys\nimport target\n'
        'def test_nested(tmp_path):\n'
        '    assert target.used() == 1\n'
        '    assert "COVERAGE_FILE" not in os.environ\n'
        '    (tmp_path / "child.py").write_text("value = 1\\n")\n'
        '    (tmp_path / "pytest.ini").write_text("[pytest]\\n")\n'
        '    (tmp_path / "test_child.py").write_text("import child\\ndef test_child(): assert child.value == 1\\n")\n'
        '    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", '
        '"--cov=child", "--cov-report=term"], cwd=tmp_path, capture_output=True, text=True)\n'
        '    assert proc.returncode == 0, proc.stdout + proc.stderr\n', encoding="utf-8")
    monkeypatch.setattr(bench, "fingerprint", lambda path: {"fixture": "unchanged"})
    # No commit is needed for this process/coverage regression. Only replace
    # the metadata call; actual parent and nested pytest execute normally.
    original_run = bench.subprocess.run

    def metadata(argv, **kwargs):
        if argv == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout="fixture-head\n")
        return original_run(argv, **kwargs)

    monkeypatch.setattr(bench.subprocess, "run", metadata)

    def command(mode, seed, output, runner):
        return [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "--cov=target",
                f"--cov-config={output / 'coverage.toml'}", f"--junitxml={output / 'junit.xml'}",
                f"--cov-report=xml:{output / 'coverage.xml'}"]

    monkeypatch.setattr(bench, "command", command)
    output = tmp_path / "evidence"
    assert bench.run(root, output, options=bench.MeasurementOptions(mode="serial", seed=17, timeout=60)) == 0
    result = json.loads((output / "result.json").read_text())
    assert result["state"] == "passed"
    assert result["junit"]["count"] == 1
    assert all("child.py" not in name for name in result["coverage"])
    assert any("target.py" in name for name in result["coverage"])



def test_record_retains_exact_head_and_tool_inventory(measurement, monkeypatch):
    names = {"pytest", "pytest-xdist", "pytest-cov", "pytest-randomly", "coverage", "execnet",
             "mutmut", "pyrefly", "ruff"}

    def metadata(argv, **kwargs):
        assert argv == ["git", "rev-parse", "HEAD"]
        assert kwargs == {"cwd": measurement[0], "capture_output": True, "text": True,
                          "check": True, "timeout": 30}
        return SimpleNamespace(stdout="  fixture-head\n")

    def version(name):
        assert name in names
        if name == "execnet":
            raise bench.importlib.metadata.PackageNotFoundError(name)
        return "fixture-version-" + name

    monkeypatch.setattr(bench.subprocess, "run", metadata)
    monkeypatch.setattr(bench.importlib.metadata, "version", version)
    assert invoke(measurement) == 0
    data = report(measurement)
    assert data["source_head"] == "fixture-head"
    assert data["versions"] == {name: None if name == "execnet" else "fixture-version-" + name for name in names}



@pytest.mark.parametrize("tag", ["failure", "error"])
def test_reported_test_failure_cannot_pass_even_if_pytest_returns_zero(measurement, monkeypatch, tag):
    healthy = bench.execute

    def execute(*args, **kwargs):
        healthy(*args, **kwargs)
        (measurement[1] / "junit.xml").write_text(
            f'<testsuite tests="1"><testcase name="failed"><{tag}/></testcase></testsuite>')
        return 0

    monkeypatch.setattr(bench, "execute", execute)
    assert invoke(measurement) == 1
    assert report(measurement)["state"] == "failed"



def test_unreadable_final_source_inventory_invalidates_measurement(measurement, monkeypatch):
    original = bench.fingerprint
    calls = []

    def fingerprint(root):
        calls.append(root)
        if len(calls) == 2:
            raise OSError("unreadable final source")
        return original(root)

    monkeypatch.setattr(bench, "fingerprint", fingerprint)
    assert invoke(measurement) == 1
    assert report(measurement)["source_unchanged"] is False



@pytest.mark.parametrize("config,message", [
    ("[tool.coverage.report]\n", "coverage configuration section is missing or ambiguous"),
    ('[tool.coverage.run]\ndata_file = "custom"\n', "explicit coverage data_file requires review"),
])
def test_unreviewed_coverage_configuration_does_not_start(measurement, config, message):
    (measurement[0] / "pyproject.toml").write_text(config)
    with pytest.raises(ValueError) as caught:
        invoke(measurement)
    assert str(caught.value) == message
    assert measurement[3] == []



def test_data_file_in_report_section_is_not_misread_as_run_override(measurement):
    (measurement[0] / "pyproject.toml").write_text(
        '[tool.coverage.run]\nbranch = true\n# data_file is deliberately not configured\n'
        '[tool.coverage.report]\n# fixture boundary\ndata_file_note = "not a run setting"\n')
    assert invoke(measurement) == 0



def test_record_schema_times_private_environment_and_outcomes_are_complete(measurement, monkeypatch):
    clocks = iter([100.0, 103.0])
    ticks = iter([50.0, 52.5])
    cpus = iter([2.0, 5.25])
    monkeypatch.setattr(bench.time, "time", lambda: next(clocks))
    monkeypatch.setattr(bench.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(bench, "cpu_seconds", lambda: next(cpus))
    monkeypatch.setattr(bench.platform, "platform", lambda: "fixture-platform")
    monkeypatch.setattr(bench.os, "cpu_count", lambda: 4)
    healthy = bench.execute

    def execute(argv, **kwargs):
        env = kwargs["context"].env
        keys = ("HOME", "TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
                "XDG_DATA_HOME", "XDG_STATE_HOME", "USERPROFILE")
        paths = [Path(env[key]) for key in keys]
        assert len(set(paths)) == len(keys)
        assert len({p.parent for p in paths}) == 1
        assert all(p.is_dir() for p in paths)
        assert paths[0].parent.name.startswith("arena-benchmark-")
        assert measurement[0] not in paths[0].parents
        return healthy(argv, **kwargs)

    monkeypatch.setattr(bench, "execute", execute)
    assert invoke(measurement) == 0
    data = report(measurement)
    assert data["schema"] == 1
    assert data["mode"] == "n2"
    assert data["seed"] == 17
    assert data["source_manifest"] == {"sample.py": measurement[2].read_text()}
    assert data["platform"] == "fixture-platform"
    assert data["python"] == sys.version
    assert data["logical_cpus"] == 4
    assert data["started_unix"] == 100.0
    assert data["completed_unix"] == 103.0
    assert data["wall_seconds"] == 2.5
    assert data["child_cpu_seconds"] == 3.25
    assert data["peak_memory_note"] == "not measured; no RSS estimate presented as physical peak"
    assert data["locks"] == {"requirements-ci.txt": None, "requirements-mutation.lock": None}
    assert data["pytest_exit"] == 0
    assert (measurement[1] / "pytest.log").is_file()



@pytest.mark.parametrize("failure_case", [
    (subprocess.TimeoutExpired("fixture", 1), 124, "pytest timeout; partial evidence retained, no retry"),
    (KeyboardInterrupt(), 130, "interrupted; partial evidence retained"),
    (OSError(), 1, "incomplete measurement: OSError"),
])
def test_failure_record_retains_the_diagnostic_not_only_exit_code(measurement, monkeypatch, failure_case):
    error, code, message = failure_case

    def execute(*args, **kwargs):
        raise error

    monkeypatch.setattr(bench, "execute", execute)
    assert invoke(measurement) == code
    assert report(measurement)["error"] == message



def test_unexpected_exception_leaves_a_failed_record_before_propagating(measurement, monkeypatch):
    def execute(*args, **kwargs):
        raise RuntimeError("unexpected engine failure")

    monkeypatch.setattr(bench, "execute", execute)
    with pytest.raises(RuntimeError):
        invoke(measurement)
    assert report(measurement)["state"] == "failed"
    assert report(measurement)["exit"] == 1



@pytest.mark.parametrize("refusal,message", [
    ("checkout", "output must be outside the checkout"),
    ("platform", "measurement process cleanup is validated only on Linux"),
    ("inventory", "source inventory is empty"),
])
def test_refusal_diagnostics_do_not_obscure_the_cause(measurement, monkeypatch, refusal, message):
    root, output, _, _ = measurement
    if refusal == "checkout":
        output = root / "run"
    elif refusal == "platform":
        monkeypatch.setattr(bench.platform, "system", lambda: "Darwin")
    else:
        monkeypatch.setattr(bench, "fingerprint", lambda root: {})
    with pytest.raises(ValueError) as caught:
        bench.run(root, output, options=bench.MeasurementOptions(mode="serial", seed=17, timeout=60))
    assert str(caught.value) == message



def test_harness_stays_in_zero_survivor_mutation_gate():
    from scripts.mutation_gate import TARGETS

    name = "arena/governance/benchmark_runner.py"
    assert set(TARGETS[name]) == {
        "tests/test_benchmark_runner.py", "tests/test_benchmark_process.py",
        "tests/test_benchmark_reports.py", "tests/test_benchmark_inventory.py",
        "tests/test_benchmark_environment.py", "tests/test_benchmark_cli.py",
        "tests/test_benchmark_evidence.py", "tests/_benchmark_support.py",
    }
    baseline = json.loads((bench.ROOT / "scripts/mutation_baseline.json").read_text())
    assert baseline[name] == 0



def test_coverage_library_failure_cannot_leave_a_passed_record(measurement, monkeypatch):
    from coverage.exceptions import DataError

    def unreadable(path):
        raise DataError("corrupt diagnostic database")

    monkeypatch.setattr(bench, "read_coverage", unreadable)
    assert invoke(measurement) == 1
    saved = report(measurement)
    assert saved["state"] == "failed"
    assert saved["exit"] == 1
    assert saved["error"] == "incomplete measurement: DataError"



@pytest.mark.parametrize("failure", ["configuration", "metadata"])
def test_startup_failure_retains_a_failed_record_without_reusing_directory(measurement, monkeypatch, failure):
    root, output, _, _ = measurement
    if failure == "configuration":
        (root / "pyproject.toml").write_text("# no coverage section\n")
        error_type = ValueError
    else:
        def fail(*args, **kwargs):
            raise subprocess.CalledProcessError(1, ["git"])
        monkeypatch.setattr(bench.subprocess, "run", fail)
        error_type = subprocess.CalledProcessError
    with pytest.raises(error_type):
        invoke(measurement)
    saved = report(measurement)
    assert saved["state"] == "failed"
    assert saved["exit"] == 1
    assert saved["error"] == f"initialization failed: {error_type.__name__}"
    original = (output / "result.json").read_bytes()
    with pytest.raises(FileExistsError):
        invoke(measurement)
    assert (output / "result.json").read_bytes() == original



def test_finalization_failure_still_saves_failed_record(measurement, monkeypatch):
    def refuse(output):
        raise ValueError("unsafe evidence")

    monkeypatch.setattr(bench, "private_evidence", refuse)
    assert invoke(measurement) == 1
    result = report(measurement)
    assert result["state"] == "failed"
    assert result["error"] == "evidence finalization failed: ValueError"



@pytest.mark.parametrize("error", [KeyboardInterrupt(), RuntimeError("fixture startup fault")])
def test_startup_interruption_or_unexpected_fault_is_recorded(measurement, monkeypatch, error):
    def fail(*args):
        raise error

    monkeypatch.setattr(bench, "write_coverage_config", fail)
    with pytest.raises(type(error)):
        invoke(measurement)
    result = report(measurement)
    assert result["state"] == "failed"
    assert result["exit"] == (130 if isinstance(error, KeyboardInterrupt) else 1)
    assert result["error"] == f"initialization failed: {type(error).__name__}"



def test_initial_record_is_complete_before_configuration_starts(measurement, monkeypatch):
    original = bench.write_coverage_config
    observed = []

    def configure(root, output):
        record = json.loads((output / "result.json").read_text())
        assert set(record) == {"schema", "state", "started_unix"}
        assert record["schema"] == 1
        assert record["state"] == "running"
        assert isinstance(record["started_unix"], float)
        observed.append(True)
        original(root, output)

    monkeypatch.setattr(bench, "write_coverage_config", configure)
    assert invoke(measurement) == 0
    assert observed == [True]


def test_final_inventory_validation_error_saves_a_failed_record(measurement, monkeypatch):
    original = bench.fingerprint
    calls = []

    def fingerprint(root):
        calls.append(root)
        if len(calls) == 2:
            raise ValueError("source symlink escapes the checkout")
        return original(root)

    monkeypatch.setattr(bench, "fingerprint", fingerprint)
    assert invoke(measurement) == 1
    assert report(measurement)["source_unchanged"] is False
    assert report(measurement)["state"] == "failed"


@pytest.mark.parametrize("failure", ["missing", "empty", "malformed"])
def test_success_requires_a_readable_xml_coverage_artifact(measurement, monkeypatch, failure):
    original = bench.execute

    def execute(*args, **kwargs):
        status = original(*args, **kwargs)
        xml = measurement[1] / "coverage.xml"
        if failure == "missing":
            xml.unlink()
        else:
            xml.write_bytes(b"<coverage" if failure == "malformed" else b"")
        return status

    monkeypatch.setattr(bench, "execute", execute)
    assert invoke(measurement) == 1
    assert report(measurement)["state"] == "failed"
    assert (measurement[1] / "junit.xml").exists()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), OSError("inventory unavailable"), ValueError("bad entry")])
def test_initial_inventory_failure_is_recorded_before_launch(measurement, monkeypatch, error):
    def refuse(root):
        raise error

    monkeypatch.setattr(bench, "fingerprint", refuse)
    with pytest.raises(type(error)):
        invoke(measurement)
    assert report(measurement)["state"] == "failed"
    assert report(measurement)["exit"] == (130 if isinstance(error, KeyboardInterrupt) else 1)
    assert measurement[3] == []


@pytest.mark.parametrize("record,field", [
    (bench.MeasurementOptions(mode="n2", seed=271, timeout=60), "mode"),
    (bench.MeasurementClock(started=10.0, cpu=1.0), "started"),
])
def test_measurement_configuration_and_clock_cannot_be_rebound(record, field):
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        setattr(record, field, None)


@pytest.mark.parametrize("stage", ["read_junit", "read_coverage", "require_coverage_xml"])
def test_unexpected_evidence_error_cannot_publish_green_record(measurement, monkeypatch, stage):
    def broken(*args, **kwargs):
        raise RuntimeError("unexpected evidence failure")

    monkeypatch.setattr(bench, stage, broken)
    with pytest.raises(RuntimeError, match="unexpected evidence failure"):
        invoke(measurement)
    result = report(measurement)
    assert result["pytest_exit"] == 0
    assert result["state"] == "failed"
    assert result["exit"] == 1

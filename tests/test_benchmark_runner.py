"""T74: incomplete benchmark evidence must never be a successful measurement."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from arena.governance import benchmark_runner as bench


@pytest.fixture
def measurement(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    source = root / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[tool.coverage.run]\nbranch = true\n', encoding="utf-8")
    output = tmp_path / "evidence"
    monkeypatch.setattr(bench.platform, "system", lambda: "Linux")
    monkeypatch.setattr(bench, "fingerprint", lambda r: {"sample.py": source.read_text()})
    monkeypatch.setattr(bench.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="source-head\n"))
    monkeypatch.setattr(bench, "read_coverage", lambda path: {"sample.py": {"lines": [1], "arcs": [[-1, 1]]}})
    calls = []

    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        assert json.loads((output / "result.json").read_text())["state"] == "running"
        (output / "junit.xml").write_text(
            '<testsuites><testsuite><testcase classname="fixture" name="one" time="0.1"/>'
            '<testcase classname="fixture" name="two"><skipped message="fixture reason"/>'
            '</testcase></testsuite></testsuites>', encoding="utf-8")
        return 0

    monkeypatch.setattr(bench, "execute", execute)
    return root, output, source, calls


def invoke(measurement):
    root, output, _, _ = measurement
    return bench.run(root, output, mode="n2", seed=17, timeout=60)


def report(measurement):
    return json.loads((measurement[1] / "result.json").read_text())


def test_complete_measurement_preserves_command_outcomes_and_private_paths(measurement):
    assert invoke(measurement) == 0
    result = report(measurement)
    assert result["state"] == "passed"
    assert result["source_unchanged"] is True
    assert result["junit"]["count"] == 2
    assert result["junit"]["cases"][1]["reason"] == "fixture reason"
    assert result["command"][-3:] == ["-n", "2", "--max-worker-restart=0"]
    env = measurement[3][0][1]["env"]
    assert env["ARENA_TEST_EXECUTION_GUARD"] == "1"
    assert env["RUNNER_OS"] == "Linux"
    assert "COVERAGE_FILE" not in env
    assert f"--cov-config={measurement[1] / 'coverage.toml'}" in result["command"]
    assert not Path(env["HOME"]).exists()  # private scratch cleaned up
    assert result["peak_memory_bytes"] is None
    assert "env" not in result


def test_serial_command_has_no_parallel_flags(tmp_path):
    argv = bench.command("serial", 271, tmp_path, "Linux")
    assert argv[-2:] == ["-p", "no:xdist"]
    assert "-n" not in argv
    assert "--cov-fail-under=51" in argv
    parallel = bench.command("n2", 271, tmp_path, "Linux")
    assert parallel[-3:] == ["-n", "2", "--max-worker-restart=0"]


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


@pytest.mark.parametrize("content", [None, "broken XML", "<testsuites/>"])
def test_missing_malformed_or_empty_junit_fails_closed(measurement, monkeypatch, content):
    def execute(*args, **kwargs):
        if content is not None:
            (measurement[1] / "junit.xml").write_text(content)
        return 0

    monkeypatch.setattr(bench, "execute", execute)
    assert invoke(measurement) == 1
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


def test_output_cannot_overwrite_evidence_or_enter_checkout(measurement):
    assert invoke(measurement) == 0
    original = (measurement[1] / "result.json").read_bytes()
    with pytest.raises(FileExistsError):
        invoke(measurement)
    assert (measurement[1] / "result.json").read_bytes() == original
    with pytest.raises(ValueError, match="outside"):
        bench.run(measurement[0], measurement[0] / "evidence", mode="serial", seed=17, timeout=1)


def test_unvalidated_platform_does_not_launch(measurement, monkeypatch):
    monkeypatch.setattr(bench.platform, "system", lambda: "Windows")
    with pytest.raises(ValueError, match="only on Linux"):
        invoke(measurement)
    assert measurement[3] == []


def test_real_branch_database_is_read_without_rounding(tmp_path):
    from coverage import CoverageData

    path = tmp_path / ".coverage"
    source = str(tmp_path / "source.py")
    data = CoverageData(basename=str(path))
    data.add_arcs({source: [(-1, 1), (1, 2), (2, -1)]})
    data.write()
    assert bench.read_coverage(path) == {
        source: {"lines": [1, 2], "arcs": [(-1, 1), (1, 2), (2, -1)]},
    }
    with pytest.raises(ValueError, match="missing"):
        bench.read_coverage(tmp_path / "absent")


def test_contradictory_junit_inventory_is_rejected(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text('<testsuite tests="0"><testcase name="one"/></testsuite>')
    with pytest.raises(ValueError, match="contradict"):
        bench.read_junit(path)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process-group cleanup contract")
@pytest.mark.parametrize("interrupted", [False, True])
def test_owned_process_group_is_cleaned_up(monkeypatch, tmp_path, interrupted):
    calls = []

    class Process:
        pid = 12345

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            if interrupted and timeout == 10:
                raise subprocess.TimeoutExpired("fixture", 10)
            return 0

    def popen(argv, **kwargs):
        assert kwargs["start_new_session"] is True
        return Process()

    monkeypatch.setattr(bench.subprocess, "Popen", popen)
    monkeypatch.setattr(bench.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    if interrupted:
        with pytest.raises(subprocess.TimeoutExpired):
            bench.execute(["fixture"], root=tmp_path, env={}, log=None, timeout=10)
    else:
        assert bench.execute(["fixture"], root=tmp_path, env={}, log=None, timeout=10) == 0
    assert (12345, bench.signal.SIGTERM) in calls
    assert (12345, bench.signal.SIGKILL) in calls
    assert ("wait", 5) in calls
    assert calls[-1] == ("wait", None)


@pytest.mark.parametrize("args", [[], ["--mode", "auto"],
    ["--mode", "serial", "--seed", "17", "--output", "fixture", "--timeout", "0"]])
def test_invalid_cli_does_not_start_measurement(monkeypatch, args):
    def forbidden(*a, **kw):
        pytest.fail("invalid command launched a benchmark")

    monkeypatch.setattr(bench, "run", forbidden)
    with pytest.raises(SystemExit) as caught:
        bench.main(args)
    assert caught.value.code == 2


@pytest.mark.parametrize("text", [
    '<!DOCTYPE testsuite [<!ENTITY x "expanded">]><testsuite><testcase name="&x;"/></testsuite>',
    '<!ENTITY x "expanded"><testsuite><testcase/></testsuite>',
])
def test_junit_rejects_entity_declarations_before_parsing(tmp_path, text):
    path = tmp_path / "junit.xml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="declarations"):
        bench.read_junit(path)


def test_cli_installs_and_restores_interrupt_handlers(monkeypatch, tmp_path):
    before = {sig: bench.signal.getsignal(sig) for sig in (bench.signal.SIGINT, bench.signal.SIGTERM)}

    def run(*args, **kwargs):
        for sig in before:
            assert bench.signal.getsignal(sig) == bench.signal.default_int_handler
        return 0

    monkeypatch.setattr(bench, "run", run)
    assert bench.main(["--mode", "serial", "--seed", "17", "--output", str(tmp_path)]) == 0
    assert {sig: bench.signal.getsignal(sig) for sig in before} == before


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process-group cleanup contract")
def test_execute_real_successful_child(tmp_path):
    with (tmp_path / "child.log").open("w") as log:
        assert bench.execute([sys.executable, "-c", 'print("fixture complete")'],
                             root=tmp_path, env={}, log=log, timeout=10) == 0
    assert (tmp_path / "child.log").read_text().strip() == "fixture complete"


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
    assert "COVERAGE_FILE" not in measurement[3][0][1]["env"]


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
                f"--cov-config={output / 'coverage.toml'}", f"--junitxml={output / 'junit.xml'}"]

    monkeypatch.setattr(bench, "command", command)
    output = tmp_path / "evidence"
    assert bench.run(root, output, mode="serial", seed=17, timeout=60) == 0
    result = json.loads((output / "result.json").read_text())
    assert result["state"] == "passed"
    assert result["junit"]["count"] == 1
    assert all("child.py" not in name for name in result["coverage"])
    assert any("target.py" in name for name in result["coverage"])


def test_subtest_summary_counts_are_not_misreported_as_case_elements(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text('<testsuite tests="3"><testcase name="one"/></testsuite>')
    result = bench.read_junit(path)
    assert result["count"] == 1
    assert result["declared_tests"] == 3


def test_default_root_is_the_repository_not_its_parent():
    assert bench.ROOT == Path(__file__).resolve().parents[1]


def test_fingerprint_hashes_real_contents_and_uses_complete_git_inventory(tmp_path, monkeypatch):
    import hashlib

    (tmp_path / "tracked.py").write_bytes(b"tracked source\n")
    (tmp_path / "new file.py").write_bytes(b"new source\n")
    (tmp_path / "directory").mkdir()

    def listing(argv, **kwargs):
        assert argv == ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        assert kwargs == {"cwd": tmp_path, "capture_output": True, "check": True, "timeout": 30}
        return SimpleNamespace(stdout=b"tracked.py\0new file.py\0tracked.py\0missing.py\0directory\0")

    monkeypatch.setattr(bench.subprocess, "run", listing)
    assert bench.fingerprint(tmp_path) == {
        "new file.py": hashlib.sha256(b"new source\n").hexdigest(),
        "tracked.py": hashlib.sha256(b"tracked source\n").hexdigest(),
    }


def test_junit_preserves_named_outcomes_messages_and_durations(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text(
        '<testsuite tests="5"><testcase classname="suite" name="healthy" time="1.25"/>'
        '<testcase classname="suite" name="bad"><failure message="assertion"/></testcase>'
        '<testcase classname="suite" name="broken"><error message="setup"/></testcase>'
        '<testcase classname="suite" name="skipped"><skipped/></testcase>'
        '<testcase><error message="first"/><failure message="second"/></testcase></testsuite>')
    assert bench.read_junit(path) == {"count": 5, "declared_tests": 5, "cases": [
        {"id": ["suite", "healthy"], "outcome": "passed", "reason": "", "seconds": 1.25},
        {"id": ["suite", "bad"], "outcome": "failure", "reason": "assertion", "seconds": 0.0},
        {"id": ["suite", "broken"], "outcome": "error", "reason": "setup", "seconds": 0.0},
        {"id": ["suite", "skipped"], "outcome": "skipped", "reason": "", "seconds": 0.0},
        {"id": ["", ""], "outcome": "error", "reason": "first", "seconds": 0.0},
    ]}


def test_junit_rejects_doctype_even_without_entities(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text('<!DOCTYPE testsuite><testsuite><testcase/></testsuite>')
    with pytest.raises(ValueError, match="^JUnit declarations are not allowed$"):
        bench.read_junit(path)


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


def test_cpu_measurement_sums_child_user_and_system_time(monkeypatch):
    monkeypatch.setitem(sys.modules, "resource", SimpleNamespace(
        RUSAGE_CHILDREN="child-fixture", getrusage=lambda who: SimpleNamespace(ru_utime=1.5, ru_stime=2.25)))
    assert bench.cpu_seconds() == 3.75
    monkeypatch.setitem(sys.modules, "resource", None)
    assert bench.cpu_seconds() is None


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


def test_measurement_creates_nested_external_output_directories(measurement):
    root, output, source, calls = measurement
    nested = output / "nested" / "run"
    # This test exercises directory preparation; refuse launching pytest once
    # the destination exists, keeping it separate from the suite's test engine.
    config = root / "pyproject.toml"
    config.write_text("no coverage section")
    with pytest.raises(ValueError, match="coverage configuration section"):
        bench.run(root, nested, mode="serial", seed=17, timeout=60)
    assert nested.is_dir()
    assert calls == []


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
        env = kwargs["env"]
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


@pytest.mark.parametrize("cpu_values", [(None, None), (None, 3.0), (3.0, None)])
def test_unavailable_cpu_endpoint_is_unknown_not_an_invented_metric(measurement, monkeypatch, cpu_values):
    values = iter(cpu_values)
    monkeypatch.setattr(bench, "cpu_seconds", lambda: next(values))
    assert invoke(measurement) == 0
    assert report(measurement)["child_cpu_seconds"] is None


@pytest.mark.parametrize("error,code,message", [
    (subprocess.TimeoutExpired("fixture", 1), 124, "pytest timeout; partial evidence retained, no retry"),
    (KeyboardInterrupt(), 130, "interrupted; partial evidence retained"),
    (OSError(), 1, "incomplete measurement: OSError"),
])
def test_failure_record_retains_the_diagnostic_not_only_exit_code(measurement, monkeypatch, error, code, message):
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


@pytest.mark.parametrize("body,message", [
    ("<testsuites/>", "JUnit contains no cases"),
    ('<testsuite tests="0"><testcase/></testsuite>', "JUnit counters contradict the case inventory"),
])
def test_invalid_junit_diagnostics_are_actionable(tmp_path, body, message):
    path = tmp_path / "junit.xml"
    path.write_text(body)
    with pytest.raises(ValueError) as caught:
        bench.read_junit(path)
    assert str(caught.value) == message


@pytest.mark.parametrize("exists,arcs,message", [
    (False, False, "coverage database missing"),
    (True, False, "branch coverage missing"),
    (True, True, "coverage contains no measured files"),
])
def test_invalid_coverage_diagnostics_are_actionable(tmp_path, monkeypatch, exists, arcs, message):
    import coverage

    path = tmp_path / ".coverage"
    if exists:
        path.touch()
    monkeypatch.setattr(coverage, "CoverageData", lambda **kw: SimpleNamespace(
        read=lambda: None, has_arcs=lambda: arcs, measured_files=lambda: []))
    with pytest.raises(ValueError) as caught:
        bench.read_coverage(path)
    assert str(caught.value) == message


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
        bench.run(root, output, mode="serial", seed=17, timeout=60)
    assert str(caught.value) == message


def test_saved_json_is_atomic_and_has_stable_human_readable_format(tmp_path):
    output = tmp_path / "result.json"
    bench.save(output, {"state": "failed", "exit": 1})
    assert output.read_text() == '{\n  "state": "failed",\n  "exit": 1\n}\n'
    assert not output.with_suffix(".tmp").exists()


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


def test_harness_stays_in_zero_survivor_mutation_gate():
    from scripts.mutation_gate import TARGETS

    name = "arena/governance/benchmark_runner.py"
    assert TARGETS[name] == ("tests/test_benchmark_runner.py",)
    baseline = json.loads((bench.ROOT / "scripts/mutation_baseline.json").read_text())
    assert baseline[name] == 0

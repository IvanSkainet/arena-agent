"""T74: incomplete benchmark evidence must never be a successful measurement."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from arena.governance import benchmark_runner as bench


@pytest.mark.skipif(sys.platform != "linux", reason="Linux waitid polling contract")
@pytest.mark.parametrize("timeout", [None, 1])
def test_wait_observation_respects_exact_deadline_and_poll_interval(monkeypatch, timeout):
    ticks = iter([10.0, 11.0])
    observations = iter([None, object()])
    sleeps = []
    monkeypatch.setattr(bench.os, "waitid", lambda *args: next(observations))
    monkeypatch.setattr(bench, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=sleeps.append))
    if timeout is None:
        bench.wait_unreaped(12345, timeout)
        assert sleeps == [0.02]
    else:
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            bench.wait_unreaped(12345, timeout)
        assert caught.value.timeout == 1
        assert caught.value.cmd == "12345"
        assert sleeps == []


def test_private_environment_preserves_only_documented_os_and_locale_controls(tmp_path, monkeypatch):
    allowed = ["PATH", "LANG", "LANGUAGE", "TZ", "TERM", "SHELL", "SYSTEMROOT", "WINDIR",
               "PATHEXT", "COMSPEC", "SSL_CERT_FILE", "SSL_CERT_DIR", "LC_ALL", "LC_MESSAGES"]
    values = {key: f"fixture-{key}" for key in allowed}
    monkeypatch.setattr(bench, "os", SimpleNamespace(environ={**values, "UNLISTED_CONTROL": "refused"}))
    actual = bench.private_environment(tmp_path, "Linux")
    assert {key: actual[key] for key in allowed} == values
    assert "UNLISTED_CONTROL" not in actual
    assert actual["ARENA_TEST_EXECUTION_GUARD"] == "1"
    assert actual["RUNNER_OS"] == "Linux"
    if sys.platform != "win32":
        import stat

        paths = [Path(value) for key, value in actual.items() if value.startswith(str(tmp_path))]
        assert paths
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in paths)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX creation permissions")
def test_json_is_private_at_creation_and_before_atomic_replacement(tmp_path, monkeypatch):
    import os
    import stat

    output = tmp_path / "result.json"
    original_open = bench.os.open
    original_replace = Path.replace
    observed = []

    def create(path, flags, mode):
        assert mode == 0o600
        descriptor = original_open(path, flags, mode)
        observed.append(stat.S_IMODE(os.fstat(descriptor).st_mode))
        return descriptor

    def replace(path, target):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        return original_replace(path, target)

    monkeypatch.setattr(bench.os, "open", create)
    monkeypatch.setattr(Path, "replace", replace)
    bench.save(output, {"state": "failed"})
    assert observed == [0o600]
    assert json.loads(output.read_text()) == {"state": "failed"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX directory permissions")
def test_nested_evidence_directories_are_finalized_private(tmp_path):
    import stat

    nested = tmp_path / "nested"
    nested.mkdir(mode=0o755)
    (nested / "report").write_text("fixture")
    bench.private_evidence(tmp_path)
    assert stat.S_IMODE(nested.stat().st_mode) == 0o700
    assert stat.S_IMODE((nested / "report").stat().st_mode) == 0o600


def test_symlink_resolved_target_mode_is_part_of_source_identity(tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"same content")
    link = tmp_path / "entry"
    try:
        link.symlink_to(target.name)
    except OSError:
        pytest.skip("symlinks unavailable")
    before = bench.source_digest(tmp_path, link.name)
    target.chmod(target.stat().st_mode ^ 0o100)
    assert bench.source_digest(tmp_path, link.name) != before


@pytest.fixture(name="measurement")
def measurement_fixture(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    source = root / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[tool.coverage.run]\nbranch = true\n', encoding="utf-8")
    output = tmp_path / "evidence"
    # Measurement contracts use a synthetic Linux runner, even on Windows.
    # CPU sampling is tested separately; never consume a host resource shim.
    monkeypatch.setattr(bench, "cpu_seconds", lambda: None)
    monkeypatch.setattr(bench, "platform", SimpleNamespace(
        system=lambda: "Linux", platform=lambda: "fixture-platform"))
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

        def wait(self):
            calls.append(("reap", self.pid))
            return 0

    def observe(pid, timeout):
        calls.append(("observe", timeout))
        if interrupted and timeout == 10:
            raise subprocess.TimeoutExpired("fixture", 10)

    def popen(argv, **kwargs):
        assert kwargs["start_new_session"] is True
        return Process()

    monkeypatch.setattr(bench.subprocess, "Popen", popen)
    monkeypatch.setattr(bench, "wait_unreaped", observe)
    monkeypatch.setattr(bench.os, "waitid", lambda *a: calls.append(("ownership", a[1])))
    monkeypatch.setattr(bench.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    if interrupted:
        with pytest.raises(subprocess.TimeoutExpired):
            bench.execute(["fixture"], root=tmp_path, env={}, log=None, timeout=10)
    else:
        assert bench.execute(["fixture"], root=tmp_path, env={}, log=None, timeout=10) == 0
    assert calls == [("observe", 10), ("ownership", 12345),
                     (12345, bench.signal.SIGTERM), ("observe", 5),
                     (12345, bench.signal.SIGKILL), ("reap", 12345)]


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

    def listing(argv, **kwargs):
        assert argv == ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        assert kwargs == {"cwd": tmp_path, "capture_output": True, "check": True, "timeout": 30}
        return SimpleNamespace(stdout=b"tracked.py\0new file.py\0tracked.py\0")

    monkeypatch.setattr(bench.subprocess, "run", listing)
    assert bench.fingerprint(tmp_path) == {
        "new file.py": hashlib.sha256(json.dumps({"mode": (tmp_path / "new file.py").stat().st_mode & 0o7777}, sort_keys=True).encode() + b"\0new source\n").hexdigest(),
        "tracked.py": hashlib.sha256(json.dumps({"mode": (tmp_path / "tracked.py").stat().st_mode & 0o7777}, sort_keys=True).encode() + b"\0tracked source\n").hexdigest(),
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
    root, output, _, calls = measurement
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


@pytest.mark.parametrize("coverage_case", [
    (False, False, "coverage database missing"),
    (True, False, "branch coverage missing"),
    (True, True, "coverage contains no measured files"),
])
def test_invalid_coverage_diagnostics_are_actionable(tmp_path, monkeypatch, coverage_case):
    exists, arcs, message = coverage_case
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


def test_synthetic_linux_measurement_is_independent_of_windows_resource_shim(measurement, monkeypatch):
    monkeypatch.setitem(sys.modules, "resource", SimpleNamespace())
    assert invoke(measurement) == 0
    assert report(measurement)["child_cpu_seconds"] is None


@pytest.mark.parametrize("name", ["ARENA_TOKEN", "ARENA_STATE_HOME", "ARENA_TEST_LIVE_DEVICE",
                                 "ARENA_E2E_WHEEL", "CI", "GITHUB_ACTIONS", "PYTEST_ADDOPTS",
                                 "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "PYTEST_PLUGINS"])
def test_measurement_does_not_inherit_operator_or_test_selection_controls(measurement, monkeypatch, name):
    monkeypatch.setenv(name, "fixture-private-control")
    assert invoke(measurement) == 0
    assert name not in measurement[3][0][1]["env"]


def test_measurement_preserves_explicit_browser_skip_request(measurement, monkeypatch):
    monkeypatch.setenv("ARENA_SKIP_BROWSER_E2E", "1")
    assert invoke(measurement) == 0
    assert measurement[3][0][1]["env"]["ARENA_SKIP_BROWSER_E2E"] == "1"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux waitid ownership contract")
def test_group_is_never_signalled_after_ownership_was_lost(monkeypatch, tmp_path):
    def lost(*args):
        raise ChildProcessError("already reaped")

    monkeypatch.setattr(bench.os, "waitid", lost)
    monkeypatch.setattr(bench.os, "killpg", lambda *a: pytest.fail("signalled an unowned group"))
    with pytest.raises(ChildProcessError):
        bench.cleanup_owned_process(SimpleNamespace(pid=12345))


@pytest.mark.skipif(sys.platform != "linux", reason="Linux waitid ownership contract")
def test_real_group_leader_stays_unreaped_until_last_signal(monkeypatch, tmp_path):
    real_killpg = bench.os.killpg
    observed = []

    def killpg(pid, sig):
        # ECHILD here would mean the PID could have been recycled.
        bench.os.waitid(bench.os.P_PID, pid, bench.os.WEXITED | bench.os.WNOHANG | bench.os.WNOWAIT)
        observed.append((pid, sig))
        real_killpg(pid, sig)

    monkeypatch.setattr(bench.os, "killpg", killpg)
    with (tmp_path / "child.log").open("w") as log:
        assert bench.execute([sys.executable, "-c", "pass"], root=tmp_path, env={}, log=log, timeout=10) == 0
    assert [sig for _, sig in observed] == [bench.signal.SIGTERM, bench.signal.SIGKILL]
    with pytest.raises(ChildProcessError):
        bench.os.waitid(bench.os.P_PID, observed[0][0], bench.os.WEXITED | bench.os.WNOHANG | bench.os.WNOWAIT)


@pytest.mark.parametrize("kind", ["missing", "directory", "dangling"])
def test_git_inventory_cannot_silently_omit_an_entry(tmp_path, monkeypatch, kind):
    path = tmp_path / "entry"
    if kind == "directory":
        path.mkdir()
    elif kind == "dangling":
        try:
            path.symlink_to("absent")
        except OSError:
            pytest.skip("symlink creation unavailable")
    monkeypatch.setattr(bench.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=b"entry\0"))
    with pytest.raises((OSError, ValueError)):
        bench.fingerprint(tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode identity")
def test_source_mode_change_invalidates_identical_content(tmp_path):
    path = tmp_path / "entry"
    path.write_bytes(b"same source")
    before = bench.source_digest(tmp_path, "entry")
    path.chmod(path.stat().st_mode ^ 0o100)
    assert bench.source_digest(tmp_path, "entry") != before


def test_symlink_target_change_invalidates_identical_content(tmp_path):
    for name in ["one", "two"]:
        (tmp_path / name).write_bytes(b"identical")
    link = tmp_path / "entry"
    try:
        link.symlink_to("one")
    except OSError:
        pytest.skip("symlink creation unavailable")
    before = bench.source_digest(tmp_path, "entry")
    link.unlink()
    link.symlink_to("two")
    assert bench.source_digest(tmp_path, "entry") != before


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission contract")
def test_retained_evidence_is_private_even_with_permissive_umask(measurement):
    import os
    import stat

    old = os.umask(0)
    try:
        assert invoke(measurement) == 0
    finally:
        os.umask(old)
    output = measurement[1]
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir())


def test_evidence_privacy_refuses_links_without_changing_target(tmp_path):
    target = tmp_path / "outside"
    target.write_text("private target")
    mode = target.stat().st_mode
    output = tmp_path / "evidence"
    output.mkdir()
    try:
        (output / "report").symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="^evidence contains a symlink$"):
        bench.private_evidence(output)
    assert target.stat().st_mode == mode
    assert target.read_text() == "private target"


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


@pytest.mark.skipif(sys.platform != "linux", reason="Linux owned interruption contract")
def test_interrupt_also_signals_before_reaping(monkeypatch, tmp_path):
    calls = []

    def observe(pid, timeout):
        if timeout == 10:
            raise KeyboardInterrupt

    def reap():
        calls.append("reap")
        return -15

    monkeypatch.setattr(bench.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=12345, wait=reap))
    monkeypatch.setattr(bench, "wait_unreaped", observe)
    monkeypatch.setattr(bench.os, "waitid", lambda *a: None)
    monkeypatch.setattr(bench.os, "killpg", lambda pid, sig: calls.append(sig))
    with pytest.raises(KeyboardInterrupt):
        bench.execute(["fixture"], root=tmp_path, env={}, log=None, timeout=10)
    assert calls == [bench.signal.SIGTERM, bench.signal.SIGKILL, "reap"]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process group contract")
@pytest.mark.parametrize("timed_out", [False, True])
def test_real_descendant_cannot_outlive_owned_execution(tmp_path, timed_out):
    import time

    marker = tmp_path / "descendant.pid"
    child = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    script = (
        "import subprocess,sys,time,pathlib; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"pathlib.Path({str(marker)!r}).write_text(str(p.pid)); "
        + ("time.sleep(60)" if timed_out else "time.sleep(0.2)")
    )
    with (tmp_path / "execution.log").open("w") as log:
        if timed_out:
            with pytest.raises(subprocess.TimeoutExpired):
                bench.execute([sys.executable, "-c", script], root=tmp_path, env={}, log=log, timeout=1)
        else:
            assert bench.execute([sys.executable, "-c", script], root=tmp_path, env={}, log=log, timeout=10) == 0
    pid = int(marker.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()[0]
        except FileNotFoundError:
            return
        if state == "Z":  # Dead orphan awaits the container init's reap.
            return
        time.sleep(0.02)
    pytest.fail("owned descendant remained alive after cleanup")


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


@pytest.mark.skipif(sys.platform != "linux", reason="Linux real SIGINT contract")
def test_real_sigint_cleans_owned_group(tmp_path):
    import os
    import signal
    import time

    marker = tmp_path / "child.pid"
    child = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"
    leader = (
        "import pathlib,subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"pathlib.Path({str(marker)!r}).write_text(str(p.pid)); time.sleep(60)"
    )
    owner = (
        "import signal; signal.signal(signal.SIGINT, signal.default_int_handler); "
        "from pathlib import Path; from arena.governance.benchmark_runner import execute; "
        f"execute([{sys.executable!r},'-c',{leader!r}], root=Path({str(tmp_path)!r}), "
        "env={},log=None,timeout=30)"
    )
    proc = subprocess.Popen([sys.executable, "-c", owner], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    pid = None
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            assert proc.poll() is None, "owner exited before child startup"
            time.sleep(0.02)
        assert marker.exists(), "child startup timed out"
        pid = int(marker.read_text())
        os.kill(proc.pid, signal.SIGINT)
        assert proc.wait(timeout=10) != 0
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                state = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()[0]
            except FileNotFoundError:
                return
            if state == "Z":
                return
            time.sleep(0.02)
        pytest.fail("descendant survived SIGINT cleanup")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if pid is not None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX creation permissions")
def test_evidence_directory_is_private_before_any_chmod(measurement, monkeypatch):
    import stat

    original = Path.mkdir
    output = measurement[1]
    observed = []

    def mkdir(path, *args, **kwargs):
        original(path, *args, **kwargs)
        if path == output:
            observed.append(stat.S_IMODE(path.stat().st_mode))
            assert observed[-1] == 0o700

    monkeypatch.setattr(Path, "mkdir", mkdir)
    assert invoke(measurement) == 0
    assert observed == [0o700]


def test_source_digest_reports_external_links_and_nonfiles_precisely(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "directory").mkdir()
    with pytest.raises(ValueError, match="^source inventory contains a non-file entry$"):
        bench.source_digest(root, "directory")
    outside = tmp_path / "external"
    outside.write_text("fixture")
    try:
        (root / "link").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="^source symlink escapes the checkout$"):
        bench.source_digest(root, "link")


def test_source_digest_uses_reproducible_manifest_metadata_schema(tmp_path):
    import hashlib
    import stat

    target = tmp_path / "target"
    target.write_bytes(b"fixture content")
    link = tmp_path / "link"
    try:
        link.symlink_to(target.name)
    except OSError:
        pytest.skip("symlinks unavailable")
    # Independent schema oracle: manifest hashes must not drift across invocations.
    metadata = {"mode": stat.S_IMODE(link.lstat().st_mode), "target": "target",
                "target_mode": stat.S_IMODE(target.stat().st_mode)}
    expected = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode("utf-8")
                              + b"\0fixture content").hexdigest()
    assert bench.source_digest(tmp_path, "link") == expected

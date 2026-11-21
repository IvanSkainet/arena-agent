"""T74: private exclusive evidence and atomic JSON persistence."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from arena.governance import benchmark_runner as bench
from tests._benchmark_support import invoke, measurement_fixture as measurement_fixture


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



def test_output_cannot_overwrite_evidence_or_enter_checkout(measurement):
    assert invoke(measurement) == 0
    original = (measurement[1] / "result.json").read_bytes()
    with pytest.raises(FileExistsError):
        invoke(measurement)
    assert (measurement[1] / "result.json").read_bytes() == original
    with pytest.raises(ValueError, match="outside"):
        bench.run(measurement[0], measurement[0] / "evidence", mode="serial", seed=17, timeout=1)



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



def test_saved_json_is_atomic_and_has_stable_human_readable_format(tmp_path):
    output = tmp_path / "result.json"
    bench.save(output, {"state": "failed", "exit": 1})
    assert output.read_text() == '{\n  "state": "failed",\n  "exit": 1\n}\n'
    assert not output.with_suffix(".tmp").exists()



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


@pytest.mark.parametrize("stage", ["serialization", "replacement"])
def test_atomic_save_cleans_only_its_owned_temporary_on_failure(tmp_path, monkeypatch, stage):
    destination = tmp_path / "result.json"
    bench.save(destination, {"state": "running"})
    original = destination.read_bytes()

    def refuse(*args, **kwargs):
        raise OSError("fixture write failure")

    with monkeypatch.context() as patch:
        if stage == "serialization":
            patch.setattr(bench, "json", type("Codec", (), {"dumps": refuse}))
        else:
            patch.setattr(Path, "replace", refuse)
        with pytest.raises(OSError, match="fixture write failure"):
            bench.save(destination, {"state": "failed"})
    assert not destination.with_suffix(".tmp").exists()
    assert destination.read_bytes() == original
    bench.save(destination, {"state": "failed"})
    assert json.loads(destination.read_text()) == {"state": "failed"}


def test_atomic_save_never_removes_another_invocations_temporary(tmp_path):
    destination = tmp_path / "result.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(b"owned by another invocation")
    with pytest.raises(FileExistsError):
        bench.save(destination, {"state": "failed"})
    assert temporary.read_bytes() == b"owned by another invocation"


def test_atomic_save_preserves_post_replacement_error_when_temp_is_already_gone(tmp_path, monkeypatch):
    destination = tmp_path / "result.json"
    original_chmod = Path.chmod

    def refuse_final(path, mode):
        if path == destination:
            raise PermissionError("final permission failure")
        return original_chmod(path, mode)

    monkeypatch.setattr(Path, "chmod", refuse_final)
    with pytest.raises(PermissionError, match="^final permission failure$"):
        bench.save(destination, {"state": "failed"})
    assert not destination.with_suffix(".tmp").exists()
    assert json.loads(destination.read_text()) == {"state": "failed"}


def test_empty_coverage_xml_diagnostic_is_precise(tmp_path):
    path = tmp_path / "coverage.xml"
    path.touch()
    with pytest.raises(ValueError, match="^coverage XML is empty$"):
        bench.require_coverage_xml(path)


def test_xml_presence_probe_does_not_read_the_entire_large_report(tmp_path, monkeypatch):
    from contextlib import contextmanager

    sizes = []

    class Stream:
        def read(self, size):
            sizes.append(size)
            return b"<"

    @contextmanager
    def open_probe(*args, **kwargs):
        yield Stream()

    monkeypatch.setattr(Path, "open", open_probe)
    bench.require_coverage_xml(tmp_path / "coverage.xml")
    assert sizes == [1]

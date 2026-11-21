"""T74: private synthetic measurement fixture shared by benchmark contracts."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from arena.governance import benchmark_runner as bench


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
        (output / "coverage.xml").write_text("<coverage/>\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(bench, "execute", execute)
    return root, output, source, calls



def invoke(measurement):
    root, output, _, _ = measurement
    return bench.run(root, output, mode="n2", seed=17, timeout=60)



def report(measurement):
    return json.loads((measurement[1] / "result.json").read_text())

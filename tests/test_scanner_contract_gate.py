"""T40 fail-closed scanner execution, report, and finding policies."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "scripts" / "scanner_contract_gate.py"
SECURITY_GATE = REPO / "scripts" / "security_gate.py"


def _module():
    spec = importlib.util.spec_from_file_location("scanner_contract_gate", GATE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE_PATH), *args],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )


def _report(tmp_path: Path, value, name: str = "report.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_execution_exit_contract_distinguishes_findings_from_crashes() -> None:
    assert _run("--tool", "scanner", "--exit-code", "0", "--allowed-exits", "0,1").returncode == 0
    assert _run("--tool", "scanner", "--exit-code", "1", "--allowed-exits", "0,1").returncode == 0
    crashed = _run("--tool", "scanner", "--exit-code", "127", "--allowed-exits", "0,1")
    assert crashed.returncode == 2
    assert "execution failed" in crashed.stderr


@pytest.mark.parametrize("shape", [None, [], "clean", 0])
def test_non_object_report_is_never_clean(tmp_path: Path, shape) -> None:
    path = _report(tmp_path, shape)
    result = _run("--tool", "osv", "--report", str(path), "--format", "osv")
    assert result.returncode == 2
    assert "root must be an object" in result.stderr


def test_missing_empty_and_invalid_reports_fail_closed(tmp_path: Path) -> None:
    missing = _run("--tool", "osv", "--report", str(tmp_path / "missing.json"), "--format", "osv")
    assert missing.returncode == 2 and "missing" in missing.stderr
    empty = tmp_path / "empty.json"
    empty.write_bytes(b"")
    assert _run("--tool", "osv", "--report", str(empty), "--format", "osv").returncode == 2
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    assert _run("--tool", "osv", "--report", str(invalid), "--format", "osv").returncode == 2


def test_osv_clean_and_finding_policy(tmp_path: Path) -> None:
    clean = _report(tmp_path, {"results": []}, "clean.json")
    assert _run("--tool", "osv", "--report", str(clean), "--format", "osv", "--block", "finding").returncode == 0
    finding = _report(tmp_path, {"results": [{"source": {"path": "lock"}, "packages": []}]}, "finding.json")
    red = _run("--tool", "osv", "--report", str(finding), "--format", "osv", "--block", "finding")
    assert red.returncode == 1


def test_cyclonedx_requires_real_bom_shape(tmp_path: Path) -> None:
    valid = _report(tmp_path, {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []})
    assert _run("--tool", "syft", "--report", str(valid), "--format", "cyclonedx").returncode == 0
    bad = _report(tmp_path, {"bomFormat": "CycloneDX", "specVersion": "1.6"}, "bad.json")
    assert _run("--tool", "syft", "--report", str(bad), "--format", "cyclonedx").returncode == 2


def test_grype_critical_blocks_but_high_is_advisory(tmp_path: Path) -> None:
    def match(severity: str) -> dict:
        return {"vulnerability": {"id": "CVE-test", "severity": severity}}

    report = _report(tmp_path, {"matches": [match("High")]})
    high = _run("--tool", "grype", "--report", str(report), "--format", "grype", "--block", "critical")
    assert high.returncode == 0
    assert '"high": 1' in high.stdout
    report.write_text(json.dumps({"matches": [match("Critical")]}), encoding="utf-8")
    assert _run("--tool", "grype", "--report", str(report), "--format", "grype", "--block", "critical").returncode == 1


def test_devskim_error_blocks_warning_remains_visible(tmp_path: Path) -> None:
    def sarif(level: str) -> dict:
        return {
            "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "DevSkim"}}, "results": [{"level": level}]}],
        }

    report = _report(tmp_path, sarif("warning"))
    warning = _run("--tool", "devskim", "--report", str(report), "--format", "sarif", "--block", "error")
    assert warning.returncode == 0
    assert '"warning": 1' in warning.stdout
    report.write_text(json.dumps(sarif("error")), encoding="utf-8")
    assert _run("--tool", "devskim", "--report", str(report), "--format", "sarif", "--block", "error").returncode == 1


def test_existing_security_gate_rejects_non_object_and_missing_arrays(tmp_path: Path) -> None:
    non_object = _report(tmp_path, [], "list.json")
    result = subprocess.run(
        [sys.executable, str(SECURITY_GATE), "bandit", str(non_object)],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    missing = _report(tmp_path, {}, "missing-array.json")
    for tool in ("bandit", "semgrep", "pip-audit"):
        checked = subprocess.run(
            [sys.executable, str(SECURITY_GATE), tool, str(missing)],
            cwd=REPO,
            check=False,
            capture_output=True,
            text=True,
        )
        assert checked.returncode == 2, tool

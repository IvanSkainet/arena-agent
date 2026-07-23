"""Tests for the coverage-diff guard.

Catches the class of bug where the guard:
- parses a coverage.xml that doesn't exist (or is malformed)
- reads a baseline that doesn't exist
- reads a baseline that's missing required fields
- miscomputes the drop (sign, units)
- silently allows too-large a drop
"""
from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

# All paths are resolved relative to the repo root. The test file lives at
# `tests/test_coverage_diff.py` in the actual repo, so `parent` is `tests/`
# and `parent.parent` is the repo root. The repo root also contains
# `scripts/` and `docs/`, so we anchor on whichever parent directory
# contains `scripts/coverage_diff.py`.
_here = Path(__file__).resolve().parent
REPO_ROOT = _here
for _candidate in (_here, _here.parent):
    if (_candidate / "scripts" / "coverage_diff.py").exists():
        REPO_ROOT = _candidate
        break
SCRIPT = REPO_ROOT / "scripts" / "coverage_diff.py"
BASELINE = REPO_ROOT / "docs" / "coverage-baseline.json"


def _write_coverage_xml(path: Path, line_rate: float = 0.536, branch_rate: float = 0.3892) -> None:
    """Write a minimal coverage.xml in the formato coverage.py produces."""
    lines_valid = 100
    lines_covered = int(round(line_rate * lines_valid))
    branches_valid = 50
    branches_covered = int(round(branch_rate * branches_valid))
    xml = (
        f'<?xml version="1.0" ?>\n'
        f'<coverage version="7.0.0" timestamp="0" lines-valid="{lines_valid}" '
        f'lines-covered="{lines_covered}" line-rate="{line_rate}" '
        f'branches-valid="{branches_valid}" branches-covered="{branches_covered}" '
        f'branch-rate="{branch_rate}" complexity="0">\n'
        f'  <sources><source>.</source></sources>\n'
        f'  <packages/>\n'
        f'</coverage>\n'
    )
    path.write_text(xml, encoding="utf-8")


def _write_baseline(path: Path, line_rate_pct: float = 53.6, branch_rate_pct: float = 38.92) -> None:
    data = {
        "version": "4.65.0",
        "line_rate_pct": line_rate_pct,
        "branch_rate_pct": branch_rate_pct,
        "lines_covered": 17240,
        "lines_valid": 32166,
        "captured_at": "2026-07-24T00:00:00Z",
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def _run(tmp_path: Path, xml_name: str = "cov.xml", baseline_name: str = "base.json", max_drop: float = 1.0) -> int:
    return subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--xml", str(tmp_path / xml_name),
            "--baseline", str(tmp_path / baseline_name),
            "--max-drop", str(max_drop),
        ],
        capture_output=True, text=True,
    ).returncode


def test_script_exists() -> None:
    assert SCRIPT.exists(), f"coverage_diff.py missing at {SCRIPT}"


def test_baseline_exists() -> None:
    assert BASELINE.exists(), f"coverage-baseline.json missing at {BASELINE}"


def test_baseline_has_required_fields() -> None:
    data = json.loads(BASELINE.read_text())
    for key in ("line_rate_pct", "branch_rate_pct", "version"):
        assert key in data, f"baseline missing key {key}"


def test_no_baseline_means_first_run(tmp_path: Path) -> None:
    """If the baseline file is missing, exit 0 (treat as first run, don't block)."""
    cov = tmp_path / "cov.xml"
    _write_coverage_xml(cov, line_rate=0.50)
    rc = _run(tmp_path, baseline_name="missing.json")
    assert rc == 0


def test_malformed_baseline_means_first_run(tmp_path: Path) -> None:
    """A baseline with garbage JSON should not crash the guard."""
    cov = tmp_path / "cov.xml"
    _write_coverage_xml(cov)
    (tmp_path / "base.json").write_text("this is not json", encoding="utf-8")
    rc = _run(tmp_path)
    assert rc == 0


def test_baseline_missing_field_means_first_run(tmp_path: Path) -> None:
    """A baseline missing line_rate_pct should not crash, just behave like first run."""
    cov = tmp_path / "cov.xml"
    _write_coverage_xml(cov)
    (tmp_path / "base.json").write_text(json.dumps({"version": "x"}), encoding="utf-8")
    rc = _run(tmp_path)
    assert rc == 0


def test_coverage_within_drop_passes(tmp_path: Path) -> None:
    cov = tmp_path / "cov.xml"
    base = tmp_path / "base.json"
    _write_coverage_xml(cov, line_rate=0.530)  # current = 53.0%
    _write_baseline(base, line_rate_pct=53.6)   # baseline = 53.6% → drop = 0.6 pp (≤ 1.0)
    rc = _run(tmp_path)
    assert rc == 0


def test_coverage_increase_passes(tmp_path: Path) -> None:
    cov = tmp_path / "cov.xml"
    base = tmp_path / "base.json"
    _write_coverage_xml(cov, line_rate=0.55)  # current = 55%
    _write_baseline(base, line_rate_pct=53.6)  # baseline = 53.6% → drop = -1.4 (increase)
    rc = _run(tmp_path)
    assert rc == 0


def test_coverage_drop_too_much_fails(tmp_path: Path) -> None:
    cov = tmp_path / "cov.xml"
    base = tmp_path / "base.json"
    _write_coverage_xml(cov, line_rate=0.50)  # current = 50%
    _write_baseline(base, line_rate_pct=53.6)  # baseline = 53.6% → drop = 3.6 pp (too much)
    rc = _run(tmp_path)
    assert rc == 1


def test_missing_coverage_xml_crashes(tmp_path: Path) -> None:
    """If the xml file doesn't exist, the script must crash loudly — silently passing
    would defeat the purpose of the guard."""
    base = tmp_path / "base.json"
    _write_baseline(base)
    rc = _run(tmp_path, xml_name="does_not_exist.xml")
    # Any non-zero exit is acceptable; the contract is "don't silently pass".
    assert rc != 0


def test_malformed_coverage_xml_crashes(tmp_path: Path) -> None:
    cov = tmp_path / "cov.xml"
    cov.write_text("<not><a><coverage></coverage></not>", encoding="utf-8")
    base = tmp_path / "base.json"
    _write_baseline(base)
    rc = _run(tmp_path)
    assert rc != 0


def test_real_coverage_xml_passes_against_baseline(tmp_path: Path) -> None:
    """The shipped baseline (53.6%) was captured from the real coverage.xml
    at v4.65.0 release time. Running the script against the same coverage.xml
    (copied into tmp) must pass — i.e. no false positive on the released state.
    """
    real_xml = REPO_ROOT / "scripts" / "_testdata" / "coverage.xml"
    if not real_xml.exists():
        pytest.skip("real coverage.xml not present in testdata")
    target = tmp_path / "cov.xml"
    target.write_bytes(real_xml.read_bytes())
    base = tmp_path / "base.json"
    base.write_bytes(BASELINE.read_bytes())
    rc = _run(tmp_path)
    assert rc == 0

"""A successful dotnet exit is insufficient when a filter matched fewer tests."""
from __future__ import annotations

import importlib.util
from xml.etree import ElementTree
from pathlib import Path
from unittest import TestCase

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_boe_upstream_results.py"
spec = importlib.util.spec_from_file_location("check_boe_upstream_results", SCRIPT)
assert spec and spec.loader
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
CHECK = TestCase()


def _report(tmp_path, rows):
    root = ElementTree.Element("{http://microsoft.com/schemas/VisualStudio/TeamTest/2010}TestRun")
    results = ElementTree.SubElement(root, "Results")
    for name, outcome in rows:
        ElementTree.SubElement(results, "UnitTestResult", testName="Game.Tests." + name, outcome=outcome)
    path = tmp_path / "result.trx"
    ElementTree.ElementTree(root).write(path)
    return path


def test_exact_three_upstream_contracts_pass(tmp_path):
    checker.check_results(_report(tmp_path, [(name, "Passed") for name in checker.REQUIRED_TESTS]))


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "failed", "skipped", "unrelated", "empty"])
def test_bad_selection_or_result_is_never_green(tmp_path, mutation):
    rows = [(name, "Passed") for name in sorted(checker.REQUIRED_TESTS)]
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(rows[0])
    elif mutation in {"failed", "skipped"}:
        rows[0] = rows[0][0], "Failed" if mutation == "failed" else "NotExecuted"
    elif mutation == "unrelated":
        rows.append(("UnrelatedTest", "Passed"))
    else:
        rows.clear()
    with CHECK.assertRaises(ValueError):
        checker.check_results(_report(tmp_path, rows))


def test_workflow_checks_the_actual_trx_after_dotnet():
    text = (SCRIPT.parents[1] / ".github/workflows/boe-contract.yml").read_text()
    CHECK.assertIn("python scripts/check_boe_upstream_results.py", text)
    CHECK.assertIn("boe-upstream-contract.trx", text)
    CHECK.assertIn("upstream dotnet contracts failed", text)
    CHECK.assertIn("DaemonAutomaticDispatch_DoesNotSendBootstrapAsSeparateGmRequest", text)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
@pytest.mark.parametrize("declaration", [
    '<!DOCTYPE TestRun [<!ENTITY attack "expanded">]>',
    '<!DOCTYPE TestRun SYSTEM "file:///never-read-external-dtd">',
])
def test_upstream_report_rejects_all_dtds(tmp_path, encoding, declaration):
    report = tmp_path / "hostile.trx"
    report.write_bytes((f'<?xml version="1.0" encoding="{encoding}"?>'
                        + declaration + '<TestRun/>').encode(encoding))
    with pytest.raises(ValueError, match="DTD declarations are forbidden"):
        checker.check_results(report)

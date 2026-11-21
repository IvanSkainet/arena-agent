"""T74: JUnit and branch-coverage report validation."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from arena.governance import benchmark_runner as bench
from tests._benchmark_support import invoke, measurement_fixture as measurement_fixture, report


@pytest.mark.parametrize("content", [None, "broken XML", "<testsuites/>"])
def test_missing_malformed_or_empty_junit_fails_closed(measurement, monkeypatch, content):
    def execute(*args, **kwargs):
        if content is not None:
            (measurement[1] / "junit.xml").write_text(content)
        return 0

    monkeypatch.setattr(bench, "execute", execute)
    assert invoke(measurement) == 1
    assert report(measurement)["state"] == "failed"



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



@pytest.mark.parametrize("text", [
    '<!DOCTYPE testsuite [<!ENTITY x "expanded">]><testsuite><testcase name="&x;"/></testsuite>',
    '<!ENTITY x "expanded"><testsuite><testcase/></testsuite>',
])
def test_junit_rejects_entity_declarations_before_parsing(tmp_path, text):
    path = tmp_path / "junit.xml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="declarations"):
        bench.read_junit(path)



def test_subtest_summary_counts_are_not_misreported_as_case_elements(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text('<testsuite tests="3"><testcase name="one"/></testsuite>')
    result = bench.read_junit(path)
    assert result["count"] == 1
    assert result["declared_tests"] == 3



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


@pytest.mark.parametrize("duration", ["nan", "inf", "-inf", "-0.01"])
def test_junit_durations_must_be_finite_and_nonnegative(tmp_path, duration):
    path = tmp_path / "junit.xml"
    path.write_text(f'<testsuite><testcase name="fixture" time="{duration}"/></testsuite>')
    with pytest.raises(ValueError, match="duration"):
        bench.read_junit(path)

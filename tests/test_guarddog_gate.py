"""The malicious-package gate must fail closed and stay quiet about noise.

osv-scanner and dependency-review answer "known CVE?". Neither answers
"is this malware?" -- a fresh typosquat has no CVE. GuardDog covers that,
but only if the gate around it distinguishes a real signal from the
descriptive `capability-*` findings that fire on every real library, and
only if an *unscanned* package is never reported as a clean one.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / ".github" / "scripts" / "guarddog_gate.py"
BASELINE = ROOT / "docs" / "guarddog-baseline.json"

sys.path.insert(0, str(ROOT))


def _load():
    spec = importlib.util.spec_from_file_location("guarddog_gate", GATE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def gate():
    return _load()


def _with_reports(gate, reports):
    gate.scan = lambda pkg: reports.get(
        pkg, {"package": pkg, "issues": 0, "results": {}}
    )
    return gate


def test_baseline_is_committed_and_parses():
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert isinstance(data["accepted"], dict)
    for pkg, rules in data["accepted"].items():
        for rule, reason in rules.items():
            assert rule.startswith(("threat-", "capability-")) or "_" in rule
            assert len(reason) > 30, f"{pkg}/{rule} needs a real justification"


def test_clean_dependencies_pass(gate):
    _with_reports(gate, {})
    assert gate.check(["aiohttp", "requests"]) == 0


def test_a_threat_finding_fails(gate):
    """The whole point: malware indicators stop the build."""
    _with_reports(gate, {"aiohttp": {
        "package": "aiohttp", "issues": 1,
        "results": {"threat-runtime-obfuscation-base64exec": [{"loc": "x"}]},
    }})
    assert gate.check(["aiohttp"]) == 1


def test_accepted_rule_on_a_different_package_still_fails(gate):
    """The baseline accepts a (package, rule) pair, not a rule globally.

    threat-process-memory is expected from psutil. The same rule firing
    on aiohttp is a different claim entirely and must not inherit the
    exemption.
    """
    _with_reports(gate, {"aiohttp": {
        "package": "aiohttp", "issues": 1,
        "results": {"threat-process-memory": [{"loc": "x"}]},
    }})
    assert gate.check(["aiohttp"]) == 1


def test_capability_findings_are_ignored(gate):
    """Descriptive findings fire on every real library; reporting them is noise."""
    _with_reports(gate, {"aiohttp": {
        "package": "aiohttp", "issues": 9,
        "results": {"capability-network-outbound": [{"loc": "x"}],
                    "capability-filesystem-read": [{"loc": "y"}]},
    }})
    assert gate.check(["aiohttp"]) == 0


def test_a_failed_download_is_not_a_pass(gate):
    """GuardDog returns issues:0 with an error when it cannot fetch a package.

    Measured against every removed typosquat (reuqests, colourama,
    requests3): the report is {"issues": 0, "errors": {...}}, which read
    naively is indistinguishable from a clean scan. That is the exact
    fail-open shape this repository keeps getting bitten by.
    """
    _with_reports(gate, {"ghost": {
        "package": "ghost", "issues": 0,
        "errors": {"download-package": "Received status code: 404 from PyPI"},
    }})
    assert gate.check(["ghost"]) == 1


def test_unparseable_output_is_not_a_pass(gate):
    _with_reports(gate, {"weird": {
        "package": "weird", "errors": {"gate": "no parseable JSON"},
    }})
    assert gate.check(["weird"]) == 1


def test_missing_baseline_fails_closed(gate, tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "BASELINE", tmp_path / "nope.json")
    with pytest.raises(SystemExit) as exc:
        gate.check(["aiohttp"])
    assert exc.value.code == 2


@pytest.mark.parametrize("body", ["{oops", "[1, 2]", '{"no_accepted_key": 1}'])
def test_unusable_baseline_fails_closed(gate, tmp_path, monkeypatch, body):
    path = tmp_path / "baseline.json"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(gate, "BASELINE", path)
    with pytest.raises(SystemExit) as exc:
        gate.check(["aiohttp"])
    assert exc.value.code == 2


def test_requirements_parsing_strips_versions_and_markers(gate):
    src = ROOT / "requirements.txt"
    names = gate._packages_from(src)
    assert "aiohttp" in names
    offenders = [n for n in names if any(c in n for c in "><=;[#")]
    assert not offenders

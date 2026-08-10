"""The dismiss button was an unlogged override of the release gate.

v4.169.25 added a gate that reads GitHub's security alerts and fails at
`medium` and above. It queries ``state=open``. Pressing Dismiss on the
website removes an alert from that query, so the gate answered "OK (no
open alerts in any feed)" while 294 alerts sat dismissed -- 78 high or
critical. Ivan saw them in the UI and asked again; the pipeline still
reported clean.

These tests hold the second gate to the shape that makes it worth
having: it fails on a dismissal the tree does not admit to, it stays
quiet when an alert is genuinely fixed, and it never reports a clean
repository when it could not read one.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE = REPO_ROOT / "scripts" / "dismissed_alerts_gate.py"
BASELINE = REPO_ROOT / "security_dismissals.json"


def _load_gate():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dismissed_gate", GATE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _alert(rule_id: str, severity: str = "high", reason: str = "won't fix"):
    return {"number": 1, "dismissed_reason": reason,
            "rule": {"id": rule_id, "security_severity_level": severity}}


def test_baseline_exists_and_parses():
    """The record has to be in the tree, or the gate has nothing to compare."""
    assert BASELINE.exists(), "security_dismissals.json is the record; it must be committed"
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert isinstance(data.get("rules"), dict) and data["rules"], "empty record is not a record"
    for rid, entry in data["rules"].items():
        assert isinstance(entry.get("dismissed"), int), f"{rid} has no count"
        assert entry["dismissed"] > 0, f"{rid} recorded with zero dismissals"
        assert entry.get("reasons"), f"{rid} records no reason"


def test_a_new_dismissal_fails_the_gate():
    """The whole point: one extra dismissal on the website turns CI red."""
    gate = _load_gate()
    live = gate.summarise([_alert("py/path-injection") for _ in range(7)])
    base = {"py/path-injection": {"severity": "high", "dismissed": 6, "reasons": {}}}
    problems = gate.compare(live, base)
    assert problems, "a dismissal beyond the record must fail"
    assert "1 new" in problems[0]


def test_a_wholly_unrecorded_rule_fails_the_gate():
    """A brand-new finding closed by hand leaves no diff -- unless this fires."""
    gate = _load_gate()
    live = gate.summarise([_alert("py/command-line-injection", "critical")])
    problems = gate.compare(live, {"py/path-injection": {"dismissed": 4}})
    assert problems and "not recorded" in problems[0]


def test_fixing_an_alert_does_not_fail_the_gate():
    """Reverse sabotage: honest work must not be punished.

    If fixing an alert for real forced an edit to the baseline, the
    baseline would be regenerated reflexively and stop being read. A
    count below the record is progress, not a violation.
    """
    gate = _load_gate()
    live = gate.summarise([_alert("py/path-injection")])
    base = {"py/path-injection": {"severity": "high", "dismissed": 31, "reasons": {}}}
    assert gate.compare(live, base) == [], "a shrinking count must stay green"


def test_no_dismissals_at_all_is_green():
    gate = _load_gate()
    assert gate.compare({}, {"py/path-injection": {"dismissed": 31}}) == []


def test_severity_recorded_is_the_worst_seen():
    """A rule that fires at note and at critical must not be filed as note."""
    gate = _load_gate()
    live = gate.summarise([_alert("mixed", "note"), _alert("mixed", "critical")])
    assert live["mixed"]["severity"] == "critical"


def test_reasons_are_counted_per_rule():
    gate = _load_gate()
    live = gate.summarise([
        _alert("r", reason="false positive"),
        _alert("r", reason="false positive"),
        _alert("r", reason="won't fix"),
    ])
    assert live["r"]["reasons"] == {"false positive": 2, "won't fix": 1}


def test_unreadable_is_not_reported_as_clean():
    """SKIPPED and OK must never look the same -- that hid thirteen alerts."""
    env = {k: v for k, v in __import__("os").environ.items()
           if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    proc = subprocess.run([sys.executable, str(GATE)], capture_output=True,
                          text=True, env=env, timeout=120)
    assert proc.returncode == 0
    assert "SKIPPED" in proc.stdout
    assert "OK (" not in proc.stdout


def test_gate_runs_in_ci_and_preflight():
    """A gate nobody calls is a file, not a gate."""
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "dismissed_alerts_gate.py" in ci
    pre = (REPO_ROOT / "scripts" / "preflight.py").read_text(encoding="utf-8")
    assert "dismissed_alerts_gate.py" in pre


def test_baseline_is_keyed_by_rule_not_alert_number():
    """Alert numbers are reassigned on re-analysis; a number-keyed baseline churns."""
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    for rid in data["rules"]:
        assert not rid.isdigit(), f"{rid} looks like an alert number, not a rule id"


@pytest.mark.parametrize("worse,better", [
    ("critical", "high"), ("high", "medium"), ("medium", "note"),
])
def test_rank_orders_severities(worse, better):
    gate = _load_gate()
    assert gate._rank(worse) > gate._rank(better)


# --- the bumper knew about three files and the tree had four ---------------

def test_bump_version_updates_the_android_manifest():
    """v4.169.29 bumped clean and then failed the suite on a stale APK version.

    dev/bump_version.py was written before android_app/ existed and was
    never taught about it, so every release since would have burned a
    preflight round trip on test_app_version_matches_the_bridge. Fixing
    the manifest by hand each time treats the symptom; the bumper is the
    thing that was incomplete.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bump_version", REPO_ROOT / "dev" / "bump_version.py")
    assert spec and spec.loader
    bump = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bump)
    assert hasattr(bump, "_bump_android_manifest")

    manifest = REPO_ROOT / "android_app" / "AndroidManifest.xml"
    before = manifest.read_bytes()
    try:
        line = bump._bump_android_manifest("9.9.9", dry_run=True)
        assert "9.9.9" in line
        assert manifest.read_bytes() == before, "dry-run must not write"
    finally:
        manifest.write_bytes(before)


def test_bumper_covers_every_file_holding_the_bridge_version():
    """A version source the bumper does not know about is a release delayed."""
    source = (REPO_ROOT / "dev" / "bump_version.py").read_text(encoding="utf-8")
    for needed in ("constants.py", "pyproject.toml",
                   "_version_matrix.py", "AndroidManifest.xml"):
        assert needed in source, f"bump_version.py never touches {needed}"

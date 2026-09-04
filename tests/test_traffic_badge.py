"""The clone badge must stay honest, which mostly means staying fresh.

The release download counter was the obvious thing to put in a badge and
it is the wrong number: v4.169.50 reported 349 downloads of
`arena-agent-v4.169.50.zip` against 3 of `arena-agent.zip` -- the same
bytes under two names, with 0 downloads of any `.sig`. Most of that is
auto-update retries and crawlers, and it only ever grows.

`/traffic/clones` reports distinct cloners, but only over a rolling
14-day window. A value committed once is correct for a day and quietly
wrong afterwards, which is the exact failure mode of the stale claims
fixed in #231, #234 and #240. So the badge carries its measurement date
and a workflow refreshes it daily.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "render_traffic_badge.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "traffic-badge.yml"
README = REPO_ROOT / "README.md"


def _load():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("render_traffic_badge", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def badge():
    return _load()


def test_script_and_workflow_exist():
    assert SCRIPT.is_file()
    assert WORKFLOW.is_file()


def test_the_badge_block_is_in_the_readme():
    text = README.read_text(encoding="utf-8")
    assert badge_markers_present(text), "README has no badge block"


def badge_markers_present(text: str) -> bool:
    return "<!-- BEGIN TRAFFIC BADGE -->" in text and "<!-- END TRAFFIC BADGE -->" in text


def test_the_badge_states_when_it_was_measured(badge):
    """A 14-day window with no date is unreadable a week later."""
    block = badge.badge_markup(696, 39545, "2026-09-04")
    assert "2026-09-04" in block, "the measurement date is missing"
    assert "14 days" in block or "14d" in block, "the window is not stated"


def test_the_badge_explains_why_it_is_not_a_download_count(badge):
    """The reasoning has to travel with the number.

    Otherwise the next person 'improves' it back to downloads, which is
    the metric that reads 349 for 3 real users.
    """
    block = badge.badge_markup(696, 39545, "2026-09-04")
    assert "349" in block, "the evidence against download counts is missing"


def test_rendering_replaces_the_block_rather_than_appending(badge):
    """A daily job that appends would grow the README without bound."""
    first = badge.badge_markup(10, 20, "2026-01-01")
    second = badge.badge_markup(11, 21, "2026-01-02")
    doc = "intro\n\n<!-- END GENERATED METRICS -->\n\ntail\n"
    once = badge.render(doc, first)
    twice = badge.render(once, second)
    assert twice.count("<!-- BEGIN TRAFFIC BADGE -->") == 1
    assert "2026-01-01" not in twice, "the old value survived the refresh"
    assert "2026-01-02" in twice


def test_rendering_refuses_a_readme_it_cannot_place_the_badge_in(badge):
    """Silently doing nothing would leave a stale badge looking fresh."""
    with pytest.raises(SystemExit, match="no insertion point"):
        badge.render("a README with no markers and no metrics block", "x")


def test_it_fails_closed_without_a_token(badge, monkeypatch):
    """The traffic API needs push access; anonymous returns 403.

    Reporting zero would be worse than failing: the badge would read
    'nobody clones this' and look like a measurement.
    """
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="requires push access"):
        badge.fetch_uniques()


def test_the_workflow_runs_on_a_schedule():
    """A one-off run freezes the number inside a 14-day window."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = doc.get("on") or doc.get(True)
    assert "schedule" in on, (
        "no schedule: the badge would freeze at whatever the last manual "
        "run reported, inside a window that expires"
    )
    assert on["schedule"], "schedule block is empty"


def test_the_workflow_can_write_and_says_so():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = doc["jobs"]["badge"]
    assert job["permissions"]["contents"] == "write", (
        "the job commits the refreshed badge; without write it fails at push"
    )
    assert doc.get("permissions") == {}, (
        "top-level permissions must stay empty (Scorecard Token-Permissions)"
    )


def test_the_workflow_pins_and_hardens_like_the_others():
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "harden-runner" in raw, "no egress control on a job holding a token"
    assert "egress-policy: block" in raw, "audit mode on a write-enabled job"
    for line in raw.splitlines():
        if "uses:" in line:
            ref = line.split("uses:")[1].strip()
            assert "@" in ref and len(ref.split("@")[1].split()[0]) == 40, (
                f"action not pinned to a commit sha: {ref}"
            )

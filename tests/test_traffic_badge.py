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


@pytest.fixture(name="badge")
def _badge_fixture():
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
    assert job["permissions"]["contents"] == "read", (
        "the default job token must stay read-only; the dedicated token opens PRs"
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


def test_checkout_does_not_persist_the_token():
    """zizmor artipacked, caught before this shipped.

    `actions/checkout` writes the job token into `.git/config` by
    default. This job holds `contents: write` and runs on a schedule, so
    a later step -- or an uploaded artifact -- could carry a push-capable
    credential out of the runner. The push supplies the token explicitly
    instead.
    """
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "persist-credentials: false" in raw, (
        "checkout leaves a push-capable token in .git/config"
    )
    script = (REPO_ROOT / "arena" / "maintenance" / "readme_refresh.py").read_text(encoding="utf-8")
    assert "GIT_ASKPASS" in script, "authentication must not persist in the checkout"  # nosec B101 -- pytest workflow contract.
    assert 'https://x-access-token:' not in script, "token must not appear in process arguments"  # nosec B101 -- pytest workflow contract.
    assert 'secrets.README_TRAFFIC_TOKEN' in raw, "traffic needs the dedicated credential"  # nosec B101 -- pytest workflow contract.


@pytest.mark.parametrize("payload", [None, [], {}, {"uniques": True, "count": 2},
                                    {"uniques": 3, "count": 2}, {"uniques": -1, "count": 2},
                                    {"uniques": "1", "count": 2}])
def test_invalid_traffic_does_not_become_a_zero_snapshot(badge, monkeypatch, payload):
    import io
    import json

    monkeypatch.setenv("GH_TOKEN", "test-only-placeholder")
    monkeypatch.setattr(badge.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(SystemExit, match="invalid"):
        badge.fetch_uniques()


def test_badge_does_not_equate_unique_cloners_with_people(badge):
    block = badge.badge_markup(1, 2, "2026-09-05")
    assert "not verified people" in block  # nosec B101 -- truthful metrics regression.
    assert "protected PR review" in block  # nosec B101 -- refresh proposals are not merged snapshots.


def test_only_master_can_enter_the_credential_job():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = doc["jobs"]["badge"]
    assert job["if"] == "github.ref == 'refs/heads/master'"  # nosec B101 -- dispatch boundary.
    checkout = next(step for step in job["steps"] if step.get("name") == "Checkout")
    assert checkout["with"]["ref"] == "${{ github.sha }}"  # nosec B101 -- immutable trusted source.


@pytest.mark.parametrize("markers", [
    "<!-- END TRAFFIC BADGE -->\n<!-- BEGIN TRAFFIC BADGE -->",
    "<!-- END TRAFFIC BADGE -->",
    "<!-- BEGIN TRAFFIC BADGE -->",
    "<!-- BEGIN TRAFFIC BADGE --><!-- END TRAFFIC BADGE --><!-- END TRAFFIC BADGE -->",
])
def test_malformed_markers_fail_without_inserting_another_block(badge, markers):
    readme = "<!-- END GENERATED METRICS -->\n" + markers
    with pytest.raises(SystemExit, match="malformed marker"):
        badge.render(readme, "replacement")

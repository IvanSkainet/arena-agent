"""Harden-Runner step names must not lie about the enforcement mode.

While converting jobs from `audit` to `block`, 21 steps kept the name
"Harden Runner (audit mode, egress visibility)" while actually blocking
traffic. Anyone debugging a dropped connection would read the step name and
conclude the runner was only watching.

Misleading documentation is its own defect class here, so this is checked
rather than left to review.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))


def _jobs():
    for wf in WORKFLOWS:
        data = yaml.safe_load(wf.read_text(encoding="utf-8"))
        for job_id, job in (data.get("jobs") or {}).items():
            yield wf.name, job_id, job


def _harden_runner_step(job):
    """The job's Harden-Runner step, or None if it has none."""
    for step in job.get("steps") or []:
        if "harden-runner" in str(step.get("uses", "")):
            return step
    return None


def _harden_runner_steps():
    for wf_name, job_id, job in _jobs():
        step = _harden_runner_step(job)
        if step is not None:
            yield wf_name, job_id, step


def _installs_from_pypi(job) -> bool:
    runs = " ".join(str(s.get("run", "")) for s in job.get("steps") or [])
    return "pip install" in runs or "pip download" in runs


def _allows_pypi(step) -> bool:
    """True only if pypi.org is a whole allowlist entry.

    Deliberately not a substring test: `"pypi.org" in endpoints` also matches
    evil-pypi.org.attacker.net. CodeQL flagged exactly that as
    py/incomplete-url-substring-sanitization.
    """
    endpoints = str((step.get("with") or {}).get("allowed-endpoints", "")).split()
    return any(e.split(":")[0] == "pypi.org" for e in endpoints)


def test_workflows_exist():
    assert WORKFLOWS, "no workflow files found"


def test_every_harden_runner_declares_a_policy():
    missing = [
        f"{wf}:{job}"
        for wf, job, step in _harden_runner_steps()
        if not (step.get("with") or {}).get("egress-policy")
    ]
    assert not missing, f"Harden-Runner without an explicit egress-policy: {missing}"


@pytest.mark.parametrize("policy,forbidden", [("block", "audit"), ("audit", "block")])
def test_step_name_matches_enforcement_mode(policy, forbidden):
    wrong = [
        f"{wf}:{job} -> {step.get('name')!r}"
        for wf, job, step in _harden_runner_steps()
        if (step.get("with") or {}).get("egress-policy") == policy
        and forbidden in str(step.get("name", "")).lower()
    ]
    assert not wrong, (
        f"these steps run in {policy} mode but their name says {forbidden}: {wrong}"
    )


def test_blocking_steps_list_their_allowed_endpoints():
    """block mode with no allowlist would drop everything, including GitHub."""
    missing = [
        f"{wf}:{job}"
        for wf, job, step in _harden_runner_steps()
        if (step.get("with") or {}).get("egress-policy") == "block"
        and not (step.get("with") or {}).get("allowed-endpoints")
    ]
    assert not missing, f"block mode without allowed-endpoints: {missing}"


def test_pypi_endpoints_only_where_pip_is_used():
    """An allowlist that grants more than the job needs is not an allowlist.

    Checked in both directions: a job that pip-installs must be able to reach
    PyPI, and a job that does not must not be handed the endpoint anyway.
    """
    wrong = []
    for wf_name, job_id, job in _jobs():
        step = _harden_runner_step(job)
        if step is None or (step.get("with") or {}).get("egress-policy") != "block":
            continue
        needs, allowed = _installs_from_pypi(job), _allows_pypi(step)
        if needs and not allowed:
            wrong.append(f"{wf_name}:{job_id} pip-installs but cannot reach PyPI")
        if allowed and not needs:
            wrong.append(f"{wf_name}:{job_id} is allowed PyPI but never installs anything")
    assert not wrong, wrong

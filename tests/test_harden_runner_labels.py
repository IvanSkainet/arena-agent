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


def _harden_runner_steps():
    for wf in WORKFLOWS:
        data = yaml.safe_load(wf.read_text(encoding="utf-8"))
        for job_id, job in (data.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                if "harden-runner" in str(step.get("uses", "")):
                    yield wf.name, job_id, step


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
    for wf, job, step in _harden_runner_steps():
        with_ = step.get("with") or {}
        if with_.get("egress-policy") != "block":
            continue
        endpoints = str(with_.get("allowed-endpoints", ""))
        has_pypi = "pypi.org" in endpoints
        data = yaml.safe_load(
            (Path(__file__).resolve().parents[1] / ".github" / "workflows" / wf).read_text(
                encoding="utf-8"
            )
        )
        runs = " ".join(str(s.get("run", "")) for s in data["jobs"][job].get("steps") or [])
        needs_pypi = "pip install" in runs or "pip download" in runs
        if needs_pypi and not has_pypi:
            wrong.append(f"{wf}:{job} pip-installs but cannot reach PyPI")
        if has_pypi and not needs_pypi:
            wrong.append(f"{wf}:{job} is allowed PyPI but never installs anything")
    assert not wrong, wrong

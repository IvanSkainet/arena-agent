"""Governance surfaces and aggregate required checks must fail closed."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
FORMS = REPO / ".github" / "ISSUE_TEMPLATE"
PR_TEMPLATE = REPO / ".github" / "pull_request_template.md"
REVIEW_TRIAGE = REPO / "docs" / "PR_REVIEW_TRIAGE.md"
APP_SURVEY = REPO / "docs" / "github_apps_actions_survey.md"
GATE = REPO / ".github" / "scripts" / "required_jobs_gate.py"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
SECURITY_WORKFLOW = REPO / ".github" / "workflows" / "security-scan.yml"
yaml = pytest.importorskip("yaml")

CI_BLOCKING = {
    "changes",
    "actionlint",
    "test",
    "coverage-diff",
    "version-sync",
    "changelog-freshness",
    "catalogue-harden",
    "lint",
    "packaging-e2e",
    "dashboard-browser-e2e",
    "e2e-installed",
    "js-lint",
    "quality-scan",
    "legacy-name-guard",
    "catalogue-consistency",
    "dead-dispatch",
    "json-schema-check",
    "handler-signature",
    "handler-namespace-consistency",
    "namespace-doc-coverage",
    "contract",
    "android",
}
SECURITY_BLOCKING = {
    "bandit",
    "semgrep",
    "trufflehog",
    "gitleaks",
    "security-alerts",
    "osv-scanner",
    "sbom-and-grype",
    "socket-firewall",
    "devskim",
    "pip-audit",
}


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path} must contain a YAML object"
    return data


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("required_jobs_gate", GATE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _needs_payload(names: set[str], result: str = "success") -> dict[str, dict[str, object]]:
    return {name: {"result": result, "outputs": {}} for name in names}


def _run_gate(
    expected: set[str],
    payload: object | None,
    *,
    raw: str | None = None,
    allowed_skipped: set[str] | None = None,
    policy: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if raw is not None:
        env["NEEDS_JSON"] = raw
    elif payload is not None:
        env["NEEDS_JSON"] = json.dumps(payload)
    else:
        env.pop("NEEDS_JSON", None)
    command = [sys.executable, str(GATE), "--expected", ",".join(sorted(expected))]
    if allowed_skipped is not None:
        command.extend([
            "--allow-skipped",
            ",".join(sorted(allowed_skipped)),
            "--allow-skipped-when-env",
            "DOCS_ONLY",
        ])
        if policy is None:
            env.pop("DOCS_ONLY", None)
        else:
            env["DOCS_ONLY"] = policy
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_issue_forms_are_structured_and_private_security_has_a_route() -> None:
    config = _load_yaml(FORMS / "config.yml")
    assert config["blank_issues_enabled"] is False
    links = config.get("contact_links") or []
    assert any("security/advisories/new" in str(link.get("url")) for link in links)

    required_forms = {"bug.yml", "feature.yml", "live-e2e.yml"}
    assert required_forms <= {path.name for path in FORMS.glob("*.yml")}
    for name in required_forms:
        form = _load_yaml(FORMS / name)
        assert form.get("name") and form.get("description")
        body = form.get("body")
        assert isinstance(body, list) and body
        textareas = [field for field in body if field.get("type") == "textarea"]
        assert textareas
        assert all(field.get("id") for field in textareas)
        assert any(field.get("id") in {"live_evidence", "live_plan", "sabotage"} for field in body)


def test_pr_template_requires_traceability_sabotage_and_live_evidence() -> None:
    text = PR_TEMPLATE.read_text(encoding="utf-8")
    for required in (
        "Closes #",
        "Task Board ID",
        "Root cause and invariant",
        "Bilateral sabotage",
        "Live E2E evidence",
        "Security and release impact",
        "Cross-repository impact",
        "PR_REVIEW_TRIAGE.md",
    ):
        assert required in text


def test_automated_review_triage_reads_every_surface_and_records_disposition() -> None:
    text = REVIEW_TRIAGE.read_text(encoding="utf-8")
    assert (
        "pr-review-surfaces: "
        "review-threads,submitted-reviews,ordinary-pr-comments,check-rollup"
    ) in text
    assert (
        "pr-review-dispositions: "
        "accepted,partially-accepted,rejected,duplicate,follow-up,noise"
    ) in text
    assert "pr-review-apps: keep=coderabbit,sourcery;remove=deepsource;sample-min=10" in text
    assert "## Validate before resolving" in text
    assert "## Generated autofix branches" in text

    survey = APP_SURVEY.read_text(encoding="utf-8")
    assert "ai-review-policy: keep=coderabbit,sourcery;remove=deepsource;sample-min=10" in survey


def test_ci_aggregate_names_every_blocking_job_and_excludes_debt_noise() -> None:
    workflow = _load_yaml(CI_WORKFLOW)
    jobs = workflow["jobs"]
    aggregate = jobs["ci-required"]
    assert aggregate["name"] == "CI required"
    assert "always()" in str(aggregate["if"])
    assert set(aggregate["needs"]) == CI_BLOCKING
    assert set(jobs) == CI_BLOCKING | {"debt-visibility", "ci-required"}
    assert aggregate["permissions"] == {"contents": "read"}
    run = "\n".join(str(step.get("run", "")) for step in aggregate["steps"])
    assert ".github/scripts/required_jobs_gate.py" in run
    expected = re.search(r'--expected\s+"([^"]+)"', run)
    assert expected
    assert set(expected.group(1).split(",")) == CI_BLOCKING


def test_security_aggregate_names_every_security_job() -> None:
    workflow = _load_yaml(SECURITY_WORKFLOW)
    jobs = workflow["jobs"]
    aggregate = jobs["security-required"]
    assert aggregate["name"] == "Security required"
    assert "always()" in str(aggregate["if"])
    assert set(aggregate["needs"]) == SECURITY_BLOCKING
    assert set(jobs) == SECURITY_BLOCKING | {"security-required"}
    assert aggregate["permissions"] == {"contents": "read"}
    run = "\n".join(str(step.get("run", "")) for step in aggregate["steps"])
    assert set(run.split('"')[-2].split(",")) == SECURITY_BLOCKING


def test_required_jobs_gate_accepts_only_the_exact_all_success_shape() -> None:
    module = _load_gate()
    healthy = _needs_payload(CI_BLOCKING)
    assert module.gate_errors(healthy, sorted(CI_BLOCKING)) == []

    failed = _needs_payload(CI_BLOCKING)
    failed["test"]["result"] = "failure"
    assert any("test" in error and "failure" in error for error in module.gate_errors(failed, sorted(CI_BLOCKING)))

    cancelled = _needs_payload(CI_BLOCKING)
    cancelled["android"]["result"] = "cancelled"
    assert module.gate_errors(cancelled, sorted(CI_BLOCKING))

    skipped = _needs_payload(CI_BLOCKING)
    skipped["lint"]["result"] = "skipped"
    assert module.gate_errors(skipped, sorted(CI_BLOCKING))

    missing = _needs_payload(CI_BLOCKING - {"contract"})
    assert any("missing prerequisite: contract" == error for error in module.gate_errors(missing, sorted(CI_BLOCKING)))

    unexpected = _needs_payload(CI_BLOCKING | {"unreviewed-job"})
    assert any("unexpected prerequisite: unreviewed-job" == error for error in module.gate_errors(unexpected, sorted(CI_BLOCKING)))

    assert module.gate_errors({}, sorted(CI_BLOCKING))
    assert module.gate_errors([], sorted(CI_BLOCKING))


def test_required_jobs_gate_cli_bilateral_sabotage() -> None:
    healthy = _run_gate(SECURITY_BLOCKING, _needs_payload(SECURITY_BLOCKING))
    assert healthy.returncode == 0, healthy.stderr
    assert "gate passed" in healthy.stdout

    sabotaged = _needs_payload(SECURITY_BLOCKING)
    sabotaged["gitleaks"]["result"] = "failure"
    red = _run_gate(SECURITY_BLOCKING, sabotaged)
    assert red.returncode == 1
    assert "gitleaks" in red.stdout

    malformed = _run_gate(SECURITY_BLOCKING, None, raw="not-json")
    assert malformed.returncode == 2
    assert "input error" in malformed.stderr

    absent = _run_gate(SECURITY_BLOCKING, None)
    assert absent.returncode == 2
    assert "is absent" in absent.stderr


def test_docs_only_skip_requires_an_explicit_true_policy_and_allowlist() -> None:
    expensive = {
        "test",
        "coverage-diff",
        "packaging-e2e",
        "dashboard-browser-e2e",
        "e2e-installed",
        "js-lint",
        "quality-scan",
        "android",
    }
    payload = _needs_payload(CI_BLOCKING)
    for name in expensive:
        payload[name]["result"] = "skipped"

    allowed = _run_gate(
        CI_BLOCKING,
        payload,
        allowed_skipped=expensive,
        policy="true",
    )
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr

    code_change = _run_gate(
        CI_BLOCKING,
        payload,
        allowed_skipped=expensive,
        policy="false",
    )
    assert code_change.returncode == 1

    missing_policy = _run_gate(
        CI_BLOCKING,
        payload,
        allowed_skipped=expensive,
        policy=None,
    )
    assert missing_policy.returncode == 2

    payload["actionlint"]["result"] = "skipped"
    unlisted = _run_gate(
        CI_BLOCKING,
        payload,
        allowed_skipped=expensive,
        policy="true",
    )
    assert unlisted.returncode == 1
    assert "actionlint" in unlisted.stdout

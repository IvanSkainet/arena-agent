"""Docs-only CI optimization must save runners without weakening the verdict."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / ".github" / "scripts" / "change_scope.py"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
yaml = pytest.importorskip("yaml")

EXPENSIVE = {
    "test",
    "coverage-diff",
    "packaging-e2e",
    "dashboard-browser-e2e",
    "e2e-installed",
    "js-lint",
    "quality-scan",
    "android",
}


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("change_scope", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docs_only_classifier_is_explicit_and_fail_closed() -> None:
    module = _module()
    assert module.docs_only([
        "README.md",
        "docs/RELAY.md",
        ".github/ISSUE_TEMPLATE/bug.yml",
        ".github/pull_request_template.md",
    ])
    assert not module.docs_only([]), "an empty/unmeasurable diff must run the full suite"
    for path in (
        "arena/app.py",
        "tests/test_security.py",
        ".github/workflows/ci.yml",
        ".github/scripts/change_scope.py",
        ".github/dependabot.yml",
        "requirements-ci.lock",
        "install.sh",
    ):
        assert not module.docs_only([path]), path


def test_mixed_docs_and_code_is_not_docs_only() -> None:
    module = _module()
    assert not module.docs_only(["docs/RELAY.md", "arena/relay/store.py"])


def test_ci_wires_exact_expensive_jobs_to_the_scope_sensor() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    changes = jobs["changes"]
    assert changes["name"] == "Classify change scope"
    assert changes["outputs"]["docs_only"]
    assert changes["outputs"]["run_expensive"]

    for name in EXPENSIVE:
        job = jobs[name]
        needs = job.get("needs")
        needs_set = {needs} if isinstance(needs, str) else set(needs or [])
        assert "changes" in needs_set, name
        assert "run_expensive" in str(job.get("if", "")), name

    aggregate = jobs["ci-required"]
    assert "changes" in set(aggregate["needs"])
    env = aggregate["steps"][-1]["env"]
    assert "needs.changes.outputs.docs_only" in env["DOCS_ONLY"]
    run = str(aggregate["steps"][-1]["run"])
    assert "--allow-skipped" in run
    quoted = [part for part in run.split('"') if "," in part]
    assert any(set(part.split(",")) == EXPENSIVE for part in quoted)


def test_unlisted_ci_jobs_cannot_silently_gain_docs_only_skip() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    conditioned = {
        name
        for name, job in jobs.items()
        if "run_expensive" in str(job.get("if", ""))
    }
    assert conditioned == EXPENSIVE

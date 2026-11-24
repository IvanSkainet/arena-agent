"""Docs-only CI optimization must save runners without weakening the verdict."""
from __future__ import annotations

import importlib.util
import json
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
        "requirements-ci.txt",
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


def test_a_pull_request_runs_the_oldest_and_newest_python_on_macos() -> None:
    """Two macOS jobs on a pull request leave room for a second run in the five-job allowance."""
    module = _module()
    cells = json.loads(module.macos_cells("pull_request"))
    assert cells == [
        {"os": "macos-latest", "python-version": "3.10"},
        {"os": "macos-latest", "python-version": "3.14"},
    ]


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "schedule", ""])
def test_everything_but_a_pull_request_runs_every_python_on_macos(event: str) -> None:
    """Master keeps the full macOS matrix; an unknown event gets the full matrix too."""
    module = _module()
    cells = json.loads(module.macos_cells(event))
    assert [cell["python-version"] for cell in cells] == ["3.10", "3.11", "3.12", "3.13", "3.14"]
    assert {cell["os"] for cell in cells} == {"macos-latest"}


def test_macos_versions_follow_the_linux_and_windows_matrix() -> None:
    """Adding a Python version to the matrix without adding it to macOS fails here."""
    module = _module()
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["test"]["strategy"]["matrix"]
    assert tuple(matrix["python-version"]) == module.MACOS_ALL
    assert module.MACOS_PULL_REQUEST == (module.MACOS_ALL[0], module.MACOS_ALL[-1])


def test_ci_takes_the_macos_cells_from_the_scope_sensor() -> None:
    """The matrix, the job output and the script argument are wired together."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert jobs["changes"]["outputs"]["macos_cells"] == "${{ steps.scope.outputs.macos_cells }}"
    assert jobs["test"]["strategy"]["matrix"]["include"] == "${{ fromJSON(needs.changes.outputs.macos_cells) }}"
    scope = next(step for step in jobs["changes"]["steps"] if step.get("id") == "scope")
    assert '--event "$GITHUB_EVENT_NAME"' in scope["run"]


def test_the_outputs_carry_the_macos_cells() -> None:
    """Each output is one line, and the macOS line is JSON the matrix can read."""
    module = _module()
    lines = dict(line.split("=", 1) for line in module.output_lines(only_docs=False, event="pull_request"))
    assert lines["docs_only"] == "false"
    assert lines["run_expensive"] == "true"
    assert len(json.loads(lines["macos_cells"])) == 2
    assert all("\n" not in value for value in lines.values())


def test_a_run_on_master_is_not_cancelled_by_the_next_merge() -> None:
    """Only a pull request run is replaced by a newer one; each commit on master has its own group."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    concurrency = workflow["concurrency"]
    assert concurrency["group"] == "ci-${{ github.event_name == 'pull_request' && github.ref || github.sha }}"
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


def test_a_dying_test_process_prints_its_stacks() -> None:
    """The test step asks Python for a stack dump on a fatal error."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    step = next(step for step in workflow["jobs"]["test"]["steps"] if step.get("name") == "Run tests")
    assert step["env"]["PYTHONFAULTHANDLER"] == "1"

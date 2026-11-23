"""A CI run is re-run only when GitHub never started a job, and never when a job failed."""
from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / ".github" / "scripts" / "retry_never_started.py"
WORKFLOW = REPO / ".github" / "workflows" / "retry-never-started.yml"
CI = REPO / ".github" / "workflows" / "ci.yml"

# The two messages GitHub attached to the cancelled job of run 45263396421.
NOT_ACQUIRED = "The job was not acquired by Runner of type hosted even after multiple attempts"
CAPACITY = "Due to capacity constraints, jobs targeting macOS arm64 runners may experience longer queue times."
MAC = "Tests (Python 3.13 on macos-latest)"
NOW = datetime(2026, 11, 23, 22, 0, tzinfo=timezone.utc)


@pytest.fixture(name="retry", scope="module")
def _retry() -> ModuleType:
    """Load the script the workflow runs."""
    spec = importlib.util.spec_from_file_location("retry_never_started", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def job(number: int, name: str, conclusion: str) -> dict[str, object]:
    """Build the three fields of an Actions job that the script reads."""
    return {"id": number, "name": name, "conclusion": conclusion}


def unstarted_run() -> tuple[list[dict[str, object]], dict[int, list[str]]]:
    """Return the shape of run 45263396421: one job never started and the gate failed."""
    jobs = [
        job(1, "Tests (Python 3.13 on ubuntu-latest)", "success"),
        job(2, MAC, "cancelled"),
        job(3, "Coverage diff", "skipped"),
        job(4, "CI required", "failure"),
    ]
    return jobs, {2: [NOT_ACQUIRED, CAPACITY]}


def test_a_run_github_never_started_is_re_run(retry: ModuleType) -> None:
    """One never-started job plus the gate it broke is the case to retry."""
    jobs, annotations = unstarted_run()
    again, reason = retry.decide(jobs, annotations, 1)
    assert again is True
    assert MAC in reason


def test_a_job_that_ran_and_failed_is_never_re_run(retry: ModuleType) -> None:
    """A real failure next to a never-started job needs a person (run 45263587111)."""
    jobs, annotations = unstarted_run()
    jobs.append(job(5, "Tests (Python 3.14 on macos-latest)", "failure"))
    again, reason = retry.decide(jobs, annotations, 1)
    assert again is False
    assert "Tests (Python 3.14 on macos-latest)" in reason


def test_a_plain_failure_is_left_alone(retry: ModuleType) -> None:
    """A failed test with nothing unstarted is not this script's business (run 45193224875)."""
    jobs = [job(1, "Tests (Python 3.14 on macos-latest)", "failure"), job(2, "CI required", "failure")]
    assert retry.decide(jobs, {}, 1)[0] is False


def test_a_job_cancelled_for_another_reason_is_left_alone(retry: ModuleType) -> None:
    """A cancelled job without GitHub's message was cancelled by a person or a newer push."""
    jobs, _ = unstarted_run()
    assert retry.decide(jobs, {2: ["The operation was canceled."]}, 1)[0] is False
    assert retry.decide(jobs, {}, 1)[0] is False


def test_one_explained_and_one_unexplained_cancellation_is_left_alone(retry: ModuleType) -> None:
    """Every job that is not green must be explained, not just one of them."""
    jobs, annotations = unstarted_run()
    jobs.append(job(6, "Tests (Python 3.12 on windows-latest)", "cancelled"))
    again, reason = retry.decide(jobs, annotations, 1)
    assert again is False
    assert "windows-latest" in reason


def test_the_retries_stop(retry: ModuleType) -> None:
    """The first run and two retries, then a person reads it."""
    jobs, annotations = unstarted_run()
    assert retry.LAST_ATTEMPT == 3
    assert [retry.decide(jobs, annotations, attempt)[0] for attempt in (1, 2, 3, 4)] == [True, True, False, False]


def test_a_green_run_is_left_alone(retry: ModuleType) -> None:
    """Nothing to do when every job is green."""
    jobs = [job(1, MAC, "success"), job(2, "Coverage diff", "skipped"), job(3, "CI required", "success")]
    assert retry.decide(jobs, {}, 1)[0] is False


def test_the_gate_name_matches_ci(retry: ModuleType) -> None:
    """Renaming the gate job in ci.yml must not silently switch the retry off."""
    names = set(re.findall(r"^    name: (.+)$", CI.read_text(encoding="utf-8"), flags=re.MULTILINE))
    assert retry.CONSEQUENCES <= names
    assert f"workflows/{retry.WORKFLOW}" in CI.as_posix()


def test_only_recent_failures_are_looked_at(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """A run that failed before the look-back window is left for a person."""
    recent = {"id": 1, "updated_at": "2026-11-23T21:30:00Z"}
    old = {"id": 2, "updated_at": "2026-11-23T19:00:00Z"}
    asked: list[str] = []

    def answer(path: str, _token: str, _method: str = "GET") -> dict[str, object]:
        asked.append(path)
        return {"workflow_runs": [recent, old]}

    monkeypatch.setattr(retry, "call", answer)
    assert retry.LOOK_BACK == timedelta(hours=2)
    assert retry.recent_failed_runs("o/r", "t", NOW) == [recent]
    assert asked == ["/repos/o/r/actions/workflows/ci.yml/runs?status=failure&per_page=30"]


def test_a_retry_is_one_post_to_that_run(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """The only thing the script changes is a re-run of the failed jobs of the run it read."""
    jobs, annotations = unstarted_run()
    sent: list[tuple[str, str]] = []

    def answer(path: str, _token: str, method: str = "GET") -> object:
        sent.append((method, path))
        if "/jobs?" in path:
            return {"jobs": jobs}
        return [{"message": text} for text in annotations[2]] if "/annotations" in path else None

    monkeypatch.setattr(retry, "call", answer)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert retry.handle("o/r", {"id": 77, "run_attempt": 1}, "t") is True
    assert [entry for entry in sent if entry[0] != "GET"] == [("POST", "/repos/o/r/actions/runs/77/rerun-failed-jobs")]


def test_a_refused_run_sends_nothing(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the decision is no, no request other than reads is made."""
    jobs = [job(1, MAC, "failure"), job(2, "CI required", "failure")]
    sent: list[str] = []

    def answer(path: str, _token: str, method: str = "GET") -> object:
        sent.append(method)
        return {"jobs": jobs} if "/jobs?" in path else []

    monkeypatch.setattr(retry, "call", answer)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert retry.handle("o/r", {"id": 78, "run_attempt": 1}, "t") is False
    assert set(sent) == {"GET"}


def test_one_unreadable_run_does_not_stop_the_others(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """An API error on one run does not stop the next one, and the job ends red so it is seen."""
    seen: list[int] = []

    def handle(_repo: str, run: dict[str, int], _token: str) -> bool:
        seen.append(run["id"])
        if run["id"] == 1:
            raise OSError("HTTP Error 502: Bad Gateway")
        return False

    monkeypatch.setattr(retry, "recent_failed_runs", lambda *_: [{"id": 1}, {"id": 2}])
    monkeypatch.setattr(retry, "handle", handle)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert retry.main() == 1
    assert seen == [1, 2]


def test_a_quiet_tick_succeeds(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """With nothing failed and no API error the job is green."""
    monkeypatch.setattr(retry, "recent_failed_runs", lambda *_: [])
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert retry.main() == 0


def test_the_workflow_takes_nothing_from_the_run_it_reads() -> None:
    """The workflow runs on a schedule with a narrow token and no workflow_run trigger."""
    text = WORKFLOW.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "workflow_run" not in code
    assert "pull_request" not in code
    assert "schedule:" in code
    assert "permissions: {}" in code
    assert "actions: write" in code
    assert "contents: write" not in code
    assert "persist-credentials: false" in code
    assert "egress-policy: block" in code
    assert "python3 .github/scripts/retry_never_started.py" in code

"""A CI run is re-run only when GitHub never started a job, and never when a job failed."""
from __future__ import annotations

import http.client
import importlib.util
import re
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml

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


def paged(runs: list[dict[str, object]], asked: list[str]):
    """Answer the run listing the way the API does: by page and page size."""
    def answer(path: str, _token: str, _method: str = "GET") -> dict[str, object]:
        asked.append(path)
        size = int(re.search(r"per_page=(\d+)", path).group(1))
        page = int(re.search(r"[?&]page=(\d+)", path).group(1))
        return {"workflow_runs": runs[(page - 1) * size:page * size]}
    return answer


def test_only_recent_failures_are_looked_at(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """A run that failed before the look-back window is left for a person."""
    recent = {"id": 1, "updated_at": "2026-11-23T21:30:00Z"}
    old = {"id": 2, "updated_at": "2026-11-23T19:00:00Z"}
    asked: list[str] = []
    monkeypatch.setattr(retry, "call", paged([recent, old], asked))
    assert retry.LOOK_BACK == timedelta(hours=2)
    assert retry.recent_failed_runs("o/r", "t", NOW) == [recent]
    assert asked == ["/repos/o/r/actions/workflows/ci.yml/runs?status=failure&per_page=100&page=1"]


def test_failed_runs_beyond_the_first_page_are_read(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """With more failed runs than one page holds, the rest are still looked at."""
    runs = [{"id": number, "updated_at": "2026-11-23T21:30:00Z"} for number in range(1, 132)]
    asked: list[str] = []
    monkeypatch.setattr(retry, "call", paged(runs, asked))
    assert [run["id"] for run in retry.recent_failed_runs("o/r", "t", NOW)] == list(range(1, 132))
    assert len(asked) == 2


def test_an_old_run_that_failed_again_is_found_behind_newer_ones(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """The list is ordered by creation, so a recent failure can sit on a later page."""
    runs = [{"id": number, "updated_at": "2026-11-23T10:00:00Z"} for number in range(1, 101)]
    runs.append({"id": 500, "updated_at": "2026-11-23T21:59:00Z"})
    monkeypatch.setattr(retry, "call", paged(runs, []))
    assert [run["id"] for run in retry.recent_failed_runs("o/r", "t", NOW)] == [500]


def test_the_listing_stops_at_the_page_cap(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """A listing that never ends cannot keep the job running."""
    runs = [{"id": number, "updated_at": "2026-11-23T21:30:00Z"} for number in range(1, 1001)]
    asked: list[str] = []
    monkeypatch.setattr(retry, "call", paged(runs, asked))
    assert retry.MAX_PAGES == 3
    assert len(retry.recent_failed_runs("o/r", "t", NOW)) == 300
    assert len(asked) == 3


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
    monkeypatch.delenv("RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert retry.main() == 1
    assert seen == [1, 2]


def test_a_quiet_tick_succeeds(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """With nothing failed and no API error the job is green."""
    monkeypatch.setattr(retry, "recent_failed_runs", lambda *_: [])
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.delenv("RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert retry.main() == 0


def test_a_run_named_by_the_event_is_handled_without_a_scan(
    retry: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Started by a CI run, the job handles that run and asks for no list."""
    seen: list[dict[str, int]] = []
    monkeypatch.setattr(retry, "recent_failed_runs", lambda *_: pytest.fail("scanned"))
    monkeypatch.setattr(retry, "handle", lambda _repo, run, _token: seen.append(run))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setenv("RUN_ID", "45263396421")
    monkeypatch.setenv("RUN_ATTEMPT", "1")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert retry.main() == 0
    assert seen == [{"id": 45263396421, "run_attempt": 1}]


class FakeConnection:
    """Stand in for the HTTPS connection and remember what was asked of it."""

    def __init__(self, status: int = 200, body: bytes = b"", error: Exception | None = None) -> None:
        """Prepare the answer the connection will give."""
        self.answer = (status, body, error)
        self.sent: list[tuple[str, str, bytes | None]] = []
        self.closed = False

    def request(self, method: str, path: str, **extra: object) -> None:
        """Record the request and fail if the test asked for a failure."""
        headers = extra["headers"]
        assert isinstance(headers, dict) and headers["Authorization"] == "Bearer t"
        body = extra.get("body")
        assert body is None or isinstance(body, bytes)
        self.sent.append((method, path, body))
        if self.answer[2] is not None:
            raise self.answer[2]

    def getresponse(self) -> SimpleNamespace:
        """Return the prepared status and body."""
        status, body, _ = self.answer
        return SimpleNamespace(status=status, read=lambda: body)

    def close(self) -> None:
        """Remember that the connection was closed."""
        self.closed = True


def test_the_connection_checks_the_certificate(retry: ModuleType) -> None:
    """The TLS context verifies the certificate and the host name."""
    context = retry.tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_the_api_host_is_a_constant(retry: ModuleType) -> None:
    """Requests go to api.github.com over HTTPS and nowhere else."""
    connection = retry.connect()
    try:
        assert isinstance(connection, http.client.HTTPSConnection)
        assert (connection.host, connection.port) == ("api.github.com", 443)
    finally:
        connection.close()


def test_a_read_returns_the_decoded_body(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """A GET carries no body and its JSON answer is decoded."""
    fake = FakeConnection(200, b'{"jobs": []}')
    monkeypatch.setattr(retry, "connect", lambda: fake)
    assert retry.call("/repos/o/r/x", "t") == {"jobs": []}
    assert fake.sent == [("GET", "/repos/o/r/x", None)]
    assert fake.closed is True


def test_a_re_run_request_has_an_empty_answer(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """A POST sends an empty JSON object, and an empty 201 answer is not an error."""
    fake = FakeConnection(201, b"")
    monkeypatch.setattr(retry, "connect", lambda: fake)
    assert retry.call("/repos/o/r/actions/runs/7/rerun-failed-jobs", "t", "POST") is None
    assert fake.sent == [("POST", "/repos/o/r/actions/runs/7/rerun-failed-jobs", b"{}")]


@pytest.mark.parametrize("status", [301, 403, 404, 502])
def test_a_refused_request_is_an_error(retry: ModuleType, monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    """Anything but a 2xx answer is raised, so a refused token cannot pass for success."""
    fake = FakeConnection(status, b'{"message": "no"}')
    monkeypatch.setattr(retry, "connect", lambda: fake)
    with pytest.raises(OSError, match=f"HTTP {status}"):
        retry.call("/repos/o/r/x", "t")
    assert fake.closed is True


def test_a_broken_answer_is_the_same_kind_of_error(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """A protocol error is turned into the error the main loop already handles."""
    fake = FakeConnection(error=http.client.RemoteDisconnected("gone"))
    monkeypatch.setattr(retry, "connect", lambda: fake)
    with pytest.raises(OSError):
        retry.call("/repos/o/r/x", "t")
    fake = FakeConnection(error=http.client.BadStatusLine("x"))
    monkeypatch.setattr(retry, "connect", lambda: fake)
    with pytest.raises(retry.ApiError):
        retry.call("/repos/o/r/x", "t")
    assert fake.closed is True


def workflow_code() -> str:
    """Return the workflow without its comment lines."""
    text = WORKFLOW.read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_the_workflow_reacts_when_ci_completes() -> None:
    """The retry is started by the completion of CI; the schedule is only a fallback."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert triggers["workflow_run"] == {"workflows": ["CI"], "types": ["completed"]}
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    condition = " ".join(str(workflow["jobs"]["retry"]["if"]).split())
    assert "github.event.workflow_run.conclusion == 'failure'" in condition
    assert "github.repository == 'IvanSkainet/arena-agent'" in condition


def test_the_workflow_takes_nothing_from_the_run_it_reads() -> None:
    """The three points that make the workflow_run trigger safe here."""
    code = workflow_code()
    # 1. Default-branch code only: the checkout names no ref and keeps no credentials.
    assert "ref:" not in code
    assert "persist-credentials: false" in code
    # 2. Nothing is downloaded from the triggering run.
    assert "download-artifact" not in code
    assert "pull_request" not in code
    # 3. Three values of the event are read, and none is pasted into a script.
    assert set(re.findall(r"github\.event\.workflow_run\.(\w+)", code)) == {"id", "run_attempt", "conclusion"}
    script = code[code.index("        run: python3"):]
    assert "${{" not in script
    assert "python3 .github/scripts/retry_never_started.py" in script


def test_the_workflow_token_is_narrow() -> None:
    """The job can re-run jobs and read checks; it cannot write to the repository."""
    code = workflow_code()
    assert "permissions: {}" in code
    assert "actions: write" in code
    assert "contents: write" not in code
    assert "egress-policy: block" in code


def test_a_named_run_is_the_only_one_looked_at(retry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """Started by a CI run, the script looks at that run and does not scan."""
    monkeypatch.setattr(retry, "recent_failed_runs", lambda *_: pytest.fail("scanned"))
    runs = retry.runs_to_look_at("o/r", "t", {"RUN_ID": "45263396421", "RUN_ATTEMPT": "2"})
    assert runs == [{"id": 45263396421, "run_attempt": 2}]


@pytest.mark.parametrize("environ", [{}, {"RUN_ID": ""}, {"RUN_ID": "  ", "RUN_ATTEMPT": ""}])
def test_without_a_named_run_the_script_scans(
    retry: ModuleType, monkeypatch: pytest.MonkeyPatch, environ: dict[str, str],
) -> None:
    """On a schedule or a manual start the event names no run."""
    monkeypatch.setattr(retry, "recent_failed_runs", lambda *_: [{"id": 9, "run_attempt": 1}])
    assert retry.runs_to_look_at("o/r", "t", environ) == [{"id": 9, "run_attempt": 1}]


@pytest.mark.parametrize("named", ["7/../../x", "7?x=1", "abc", "7 8"])
def test_a_run_id_that_is_not_a_number_is_refused(retry: ModuleType, named: str) -> None:
    """Only a number can become part of a request path."""
    with pytest.raises(ValueError):
        retry.runs_to_look_at("o/r", "t", {"RUN_ID": named, "RUN_ATTEMPT": "1"})

#!/usr/bin/env python3
"""Re-run a CI run whose only problem is that GitHub never started some jobs."""
# GitHub sometimes gives up on a queued macOS job: "The job was not acquired by
# Runner of type hosted even after multiple attempts". The job is cancelled
# before any step runs, the "CI required" gate counts a cancelled job as not
# verified, and the commit goes red with no failing test (#565).
#
# The gate is right. What was missing is a retry. This script asks for one when,
# and only when, every job that is not green is either such a never-started job
# or the gate that failed because of it. A job that ran and failed is never
# retried here: that needs a person.
#
# It runs on a schedule and looks at the CI runs that failed recently. A run it
# re-runs stops being "failed" at once, so the next tick does not see it again.
from __future__ import annotations

import http.client
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

HOST = "api.github.com"
NOT_ACQUIRED = "was not acquired by Runner"
# Jobs that fail only because another job did. They are re-run together with it.
CONSEQUENCES = frozenset({"CI required"})
GREEN = frozenset({"success", "skipped", "neutral"})
# The first run and two retries. A third refusal is for a person to read.
LAST_ATTEMPT = 3
WORKFLOW = "ci.yml"
# A run that failed longer ago than this is left for a person. The schedule
# runs several times inside the window, so one missed tick loses nothing.
LOOK_BACK = timedelta(hours=2)


def never_started(job: dict[str, Any], messages: list[str]) -> bool:
    """Tell whether GitHub cancelled the job because no runner took it."""
    if job.get("conclusion") != "cancelled":
        return False
    return any(NOT_ACQUIRED in message for message in messages)


def _never_started_jobs(jobs: list[dict[str, Any]], annotations: dict[int, list[str]]) -> list[dict[str, Any]]:
    """Return the jobs GitHub cancelled without starting."""
    return [job for job in jobs if never_started(job, annotations.get(job["id"], []))]


def _other_failures(not_green: list[dict[str, Any]], unstarted: list[dict[str, Any]]) -> list[str]:
    """Name the jobs that are red for a reason of their own."""
    explained = {job["id"] for job in unstarted}
    return sorted(job["name"] for job in not_green if job["id"] not in explained and job["name"] not in CONSEQUENCES)


def decide(jobs: list[dict[str, Any]], annotations: dict[int, list[str]], attempt: int) -> tuple[bool, str]:
    """Return whether to re-run the failed jobs, and the reason in one sentence."""
    not_green = [job for job in jobs if job.get("conclusion") not in GREEN]
    unstarted = _never_started_jobs(not_green, annotations)
    if not unstarted:
        return False, "no job was left unstarted by GitHub"
    other = _other_failures(not_green, unstarted)
    if other:
        return False, f"jobs failed for another reason and need a person: {', '.join(other)}"
    names = ", ".join(sorted(job["name"] for job in unstarted))
    if attempt >= LAST_ATTEMPT:
        return False, f"attempt {attempt} is the last one; still never started: {names}"
    return True, f"GitHub never started: {names}"


class ApiError(OSError):
    """The GitHub API did not answer a request with a success status."""


def connect() -> http.client.HTTPSConnection:
    """Open the connection: a constant host, always HTTPS; only the path of a request varies."""
    return http.client.HTTPSConnection(HOST, timeout=30)


def call(path: str, token: str, method: str = "GET") -> Any:
    """Send one request to the GitHub API and return the decoded body."""
    connection = connect()
    try:
        connection.request(
            method, path, body=b"{}" if method == "POST" else None,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "retry-never-started"})
        response = connection.getresponse()
        status, body = response.status, response.read()
    except http.client.HTTPException as error:
        raise ApiError(f"{method} {path}: {error!r}") from error
    finally:
        connection.close()
    if not 200 <= status < 300:
        raise ApiError(f"{method} {path}: HTTP {status}")
    return json.loads(body) if body else None


def latest_jobs(repo: str, run_id: int, token: str) -> list[dict[str, Any]]:
    """Return every job of the latest attempt of the run."""
    jobs: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = call(f"/repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100&page={page}", token)["jobs"]
        jobs.extend(batch)
        if len(batch) < 100:
            return jobs
        page += 1


def cancelled_annotations(repo: str, jobs: list[dict[str, Any]], token: str) -> dict[int, list[str]]:
    """Return the annotation messages of each cancelled job."""
    found: dict[int, list[str]] = {}
    for job in jobs:
        if job.get("conclusion") == "cancelled":
            rows = call(f"/repos/{repo}/check-runs/{job['id']}/annotations?per_page=100", token)
            found[job["id"]] = [str(row.get("message", "")) for row in rows]
    return found


def recent_failed_runs(repo: str, token: str, now: datetime) -> list[dict[str, Any]]:
    """Return the CI runs that ended in failure within the look-back window."""
    listed = call(f"/repos/{repo}/actions/workflows/{WORKFLOW}/runs?status=failure&per_page=30", token)
    oldest = now - LOOK_BACK
    return [run for run in listed["workflow_runs"] if _when(run["updated_at"]) >= oldest]


def _when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def report(line: str) -> None:
    """Print the line and add it to the run summary when there is one."""
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(line + "\n")


def handle(repo: str, run: dict[str, Any], token: str) -> bool:
    """Look at one failed run and re-run its failed jobs if that is justified."""
    run_id, attempt = int(run["id"]), int(run["run_attempt"])
    jobs = latest_jobs(repo, run_id, token)
    retry, reason = decide(jobs, cancelled_annotations(repo, jobs, token), attempt)
    if retry:
        call(f"/repos/{repo}/actions/runs/{run_id}/rerun-failed-jobs", token, "POST")
    verdict = "failed jobs re-run" if retry else "not re-run"
    report(f"- Run {run_id}, attempt {attempt}: {verdict}. Reason: {reason}.")
    return retry


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    runs = recent_failed_runs(repo, token, datetime.now(timezone.utc))
    if not runs:
        report("No CI run ended in failure in the look-back window.")
    unread = 0
    for run in runs:
        try:
            handle(repo, run, token)
        except OSError as error:
            # The API answers 502 now and then. One run that could not be
            # handled must not stop the others; the next tick looks at it again.
            unread += 1
            report(f"- Run {run['id']}: not handled, the API call failed ({error}).")
    # Fail the job when a call failed, so a refused token is seen and not
    # buried in a summary nobody opens.
    return 1 if unread else 0


if __name__ == "__main__":
    sys.exit(main())

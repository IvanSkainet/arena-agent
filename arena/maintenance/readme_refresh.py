"""Publish measured README updates as ordinary PRs from trusted master only."""
from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404 -- trusted git/gh CLI orchestration, no shell input.
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRANCH_PREFIX = "automation/readme-metrics-"
BASE = "master"


def _diagnostic(text: str) -> str:
    token = os.environ.get("GH_TOKEN", "")
    return text.replace(token, "[REDACTED]") if token else text


def run(*args: str, env: dict[str, str] | None = None) -> str:
    # All callers below construct argv locally. No shell or downloaded commands.
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True)  # nosec B603 -- fixed trusted callers.
    if result.returncode:
        print(_diagnostic(result.stderr), file=sys.stderr)
        print(_diagnostic(result.stdout), file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, args)
    return result.stdout.strip()


def _repository() -> str:
    if not os.environ.get("GH_TOKEN"):
        raise SystemExit("Set README_TRAFFIC_TOKEN before running the publisher")
    repo = os.environ.get("GITHUB_REPOSITORY", "IvanSkainet/arena-agent")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise SystemExit("Invalid repository name")
    return repo


def _pending_review(repo: str) -> bool:
    # gh handles API pagination up to this explicit fail-closed bound.
    rows = json.loads(run(
        "gh", "pr", "list", "--repo", repo, "--state", "open", "--base", BASE,
        "--limit", "1000", "--json", "number,headRefName",
    ))
    if len(rows) >= 1000:
        raise SystemExit("PR listing may be incomplete; refusing a duplicate refresh")
    return any(row["headRefName"].startswith(BRANCH_PREFIX) for row in rows)


def _git_environment() -> dict[str, str]:
    # Git requires an executable pathname, not a shell command string.
    # This tracked helper contains no secret and is not a temporary state file.
    return {
        **os.environ,
        "GIT_ASKPASS": str(ROOT / "scripts" / "readme_git_askpass.sh"),
        "GIT_TERMINAL_PROMPT": "0",
    }


def _render_branch(repo: str, branch: str, env: dict[str, str]) -> bool:
    remote = f"https://github.com/{repo}.git"
    run("git", "-c", "credential.helper=", "fetch", remote, BASE, env=env)
    run("git", "checkout", "-b", branch, "FETCH_HEAD", env=env)
    run(sys.executable, "scripts/render_traffic_badge.py", "--write", env=env)
    run(sys.executable, "scripts/render_readme_metrics.py", env=env)
    return bool(run("git", "diff", "--", "README.md", env=env))


def _publish(repo: str, branch: str, env: dict[str, str]) -> None:
    run("git", "config", "user.name", "github-actions[bot]", env=env)
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com", env=env)
    run("git", "add", "--", "README.md", env=env)
    run("git", "commit", "-m", "docs: refresh measured README metrics", env=env)
    # Fresh branch names avoid retained squash/rebase-merged or orphaned branch
    # tips without deleting anything or using force. A failed PR-create is safe
    # to retry in the next run with another fresh branch.
    run("git", "-c", "credential.helper=", "push", f"https://github.com/{repo}.git",
        f"HEAD:refs/heads/{branch}", env=env)
    print(run(
        "gh", "pr", "create", "--repo", repo, "--base", BASE, "--head", branch,
        "--title", "docs: refresh measured README metrics",
        "--body", "Generated traffic and code metrics; clones may include automation. "
        "Normal protected review and checks must pass. This workflow never merges.", env=env,
    ))


def main() -> None:
    repo = _repository()
    if run("git", "status", "--porcelain"):
        raise SystemExit("Refusing to publish from a dirty checkout")
    if _pending_review(repo):
        print("README refresh PR pending; retaining its reviewed commit")
        return
    env = _git_environment()
    branch = BRANCH_PREFIX + uuid.uuid4().hex
    if _render_branch(repo, branch, env):
        _publish(repo, branch, env)
    else:
        print("README metrics already current")

#!/usr/bin/env python3
"""Propose generated README changes via one ordinary PR; never push master.

A dedicated README_TRAFFIC_TOKEN needs Administration:read (traffic),
Contents:write and Pull requests:write for this repository only. The default
GITHUB_TOKEN stays read-only. A PAT-created PR triggers normal required CI.
Do not churn a pending review with a new commit every scheduled invocation.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "automation/readme-metrics"
BASE = "master"


def run(*args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def main() -> int:
    if not os.environ.get("GH_TOKEN"):
        raise SystemExit("Set README_TRAFFIC_TOKEN: traffic read and protected PR publication require it")
    repo = os.environ.get("GITHUB_REPOSITORY", "IvanSkainet/arena-agent")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise SystemExit("Invalid repository name")
    if run("git", "status", "--porcelain"):
        raise SystemExit("Refusing to publish from a dirty checkout")
    # An open review is deliberately not invalidated by scheduled traffic churn.
    pending = json.loads(run("gh", "pr", "list", "--repo", repo, "--state", "open",
                             "--base", BASE, "--head", BRANCH, "--json", "number"))
    if pending:
        print("README refresh PR already pending; retaining its reviewed commit")
        return 0
    with tempfile.TemporaryDirectory(prefix="readme-git-auth-") as directory:
        helper = Path(directory) / "askpass.sh"
        helper.write_text(
            '#!/bin/sh\ncase "$1" in\n'
            '*Username*) printf "%s\\n" "x-access-token" ;;\n'
            '*) printf "%s\\n" "$GH_TOKEN" ;;\nesac\n', encoding="utf-8")
        helper.chmod(0o700)
        env = {**os.environ, "GIT_ASKPASS": str(helper), "GIT_TERMINAL_PROMPT": "0"}
        remote = f"https://github.com/{repo}.git"
        run("git", "-c", "credential.helper=", "fetch", remote, BASE, env=env)
        run("git", "checkout", "-B", BRANCH, "FETCH_HEAD", env=env)
        run(sys.executable, "scripts/render_traffic_badge.py", "--write", env=env)
        run(sys.executable, "scripts/render_readme_metrics.py", env=env)
        if not run("git", "diff", "--", "README.md", env=env):
            print("README metrics already current")
            return 0
        run("git", "config", "user.name", "github-actions[bot]", env=env)
        run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com", env=env)
        run("git", "add", "--", "README.md", env=env)
        run("git", "commit", "-m", "docs: refresh measured README metrics", env=env)
        # No token in argv/config, no force push, no direct base-branch update.
        # A divergent abandoned branch fails closed and needs normal review.
        run("git", "-c", "credential.helper=", "push", remote, f"HEAD:refs/heads/{BRANCH}", env=env)
        url = run("gh", "pr", "create", "--repo", repo, "--base", BASE, "--head", BRANCH,
                  "--title", "docs: refresh measured README metrics",
                  "--body", "Generated traffic snapshot and code metrics. Clone counts may include automation; "
                  "they are not verified people or release downloads. Normal required checks and review "
                  "must pass; this workflow does not merge or bypass protections.", env=env)
        print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

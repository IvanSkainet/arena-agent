"""The GitLab mirror script pushes master and the v* tags, never forces, and leaves no key behind."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests._git_budget import git_timeout

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mirror_to_gitlab.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "gitlab-mirror.yml"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the script is bash and runs on the Linux runner only")


class Repos:
    """A source checkout and a bare mirror, both under one temporary directory."""

    def __init__(self, base: Path):
        """Create both repositories; the source gets one commit on master."""
        self.base = base
        self.source = base / "source"
        self.mirror = base / "mirror.git"
        self.scratch = base / "scratch"
        self.scratch.mkdir()
        # The host environment, with the developer's git configuration and identity taken out of the picture.
        self.env = {**os.environ, "HOME": str(base), "TMPDIR": str(self.scratch),
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        for inherited in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_SSH_COMMAND"):
            self.env.pop(inherited, None)
        self.git(base, "init", "-q", "-b", "master", str(self.source))
        self.git(base, "init", "-q", "--bare", "-b", "master", str(self.mirror))
        self.commit("first")

    def git(self, cwd: Path, *args: str) -> str:
        done = subprocess.run(["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True,
                              timeout=git_timeout(), check=True)
        return done.stdout.strip()

    def commit(self, message: str, where: Path | None = None) -> str:
        where = where or self.source
        self.git(where, "commit", "-q", "--allow-empty", "-m", message)
        return self.git(where, "rev-parse", "HEAD")

    def mirrored(self, ref: str) -> str | None:
        done = subprocess.run(["git", "rev-parse", "--verify", "-q", ref], cwd=self.mirror, env=self.env,
                              capture_output=True, text=True, timeout=git_timeout(), check=False)
        return done.stdout.strip() or None

    def run_script(self, key: str = "not a real key", mirror: Path | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        env.update(MIRROR_URL=str(mirror or self.mirror), GITLAB_MIRROR_SSH_KEY=key)
        return subprocess.run(["bash", str(SCRIPT)], cwd=self.source, env=env, capture_output=True, text=True,
                              timeout=3 * git_timeout(), check=False)


@pytest.fixture(name="repos")
def _repos(tmp_path):
    return Repos(tmp_path)


def test_master_and_release_tags_reach_the_mirror(repos):
    head = repos.commit("second")
    repos.git(repos.source, "tag", "v1.0.0")
    repos.git(repos.source, "tag", "scratch-tag")
    done = repos.run_script()
    assert done.returncode == 0, done.stderr
    assert repos.mirrored("refs/heads/master") == head
    assert repos.mirrored("refs/tags/v1.0.0") == head
    assert repos.mirrored("refs/tags/scratch-tag") is None


def test_a_second_run_with_nothing_new_succeeds(repos):
    assert repos.run_script().returncode == 0
    assert repos.run_script().returncode == 0


def test_a_mirror_that_is_ahead_is_not_overwritten(repos):
    assert repos.run_script().returncode == 0
    other = repos.base / "other"
    repos.git(repos.base, "clone", "-q", str(repos.mirror), str(other))
    foreign = repos.commit("made on the mirror only", where=other)
    repos.git(other, "push", "-q", "origin", "master")
    repos.commit("made on the source only")
    done = repos.run_script()
    assert done.returncode != 0
    assert repos.mirrored("refs/heads/master") == foreign


def test_a_release_tag_that_differs_on_the_mirror_is_not_moved(repos):
    first = repos.git(repos.source, "rev-parse", "HEAD")
    repos.git(repos.source, "tag", "v1.0.0")
    assert repos.run_script().returncode == 0
    repos.commit("second")
    repos.git(repos.source, "tag", "-f", "v1.0.0")
    done = repos.run_script()
    assert done.returncode != 0
    assert repos.mirrored("refs/tags/v1.0.0") == first


def test_a_missing_key_stops_the_script_before_any_push(repos):
    done = repos.run_script(key="")
    assert done.returncode == 1
    assert "GITLAB_MIRROR_SSH_KEY is empty" in done.stderr
    assert repos.mirrored("refs/heads/master") is None


def test_the_key_is_not_left_on_disk(repos):
    assert repos.run_script(key="a key that must not stay").returncode == 0
    assert list(repos.scratch.iterdir()) == []


def test_the_key_is_removed_when_the_push_fails(repos):
    done = repos.run_script(key="a key that must not stay", mirror=repos.base / "no-such-repository")
    assert done.returncode != 0
    assert list(repos.scratch.iterdir()) == []


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_never_runs_for_a_pull_request():
    # PyYAML reads the key `on` as the boolean True.
    triggers = workflow()[True]
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"branches": ["master"], "tags": ["v*"]}


def test_the_key_is_given_to_the_push_step_only():
    steps = workflow()["jobs"]["mirror"]["steps"]
    holders = [step["name"] for step in steps if "secrets." in str(step)]
    assert holders == ["Push to GitLab"]
    assert steps[-1]["run"] == "scripts/mirror_to_gitlab.sh"


def test_the_checkout_takes_all_of_master_and_keeps_no_token():
    checkout = next(step for step in workflow()["jobs"]["mirror"]["steps"] if "actions/checkout@" in step.get("uses", ""))
    assert checkout["with"] == {"ref": "master", "fetch-depth": 0, "fetch-tags": True, "persist-credentials": False}


def test_the_script_pins_the_gitlab_host_key_and_never_forces():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "StrictHostKeyChecking=yes" in text
    assert "ssh-keyscan " not in text.replace("with ssh-keyscan", "")
    pushes = [line for line in text.splitlines() if line.startswith("git push")]
    assert len(pushes) == 1
    assert "--force" not in pushes[0] and "+" not in pushes[0] and "--prune" not in pushes[0] and "--mirror" not in pushes[0]

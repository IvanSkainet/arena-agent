"""The npm lock that the JS lint job installs from is watched by Dependabot."""
# package.json pins the JS linter and package-lock.json pins everything it
# pulls in. For a long time no Dependabot entry covered them, so the linter
# stayed at the version it was first pinned to while the job kept passing.
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _updates() -> list[dict]:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    return config["updates"]


def _npm_entries() -> list[dict]:
    return [update for update in _updates() if update.get("package-ecosystem") == "npm"]


def test_the_repository_still_has_an_npm_lock():
    """The premise: if the lock goes away, this file and the Dependabot entry go with it."""
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package.get("devDependencies"), "package.json pins nothing"
    assert (ROOT / "package-lock.json").is_file()


def test_dependabot_watches_the_directory_that_holds_the_lock():
    assert [entry.get("directory") for entry in _npm_entries()] == ["/"]


def test_the_js_lint_job_installs_from_that_lock():
    """The entry matters because CI installs exactly what the lock says."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "npm ci --no-audit --no-fund --ignore-scripts" in workflow

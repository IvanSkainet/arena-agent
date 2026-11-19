"""Trusted README publisher boundaries and retry behaviour."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._git_budget import git_timeout


def load_publisher():
    path = Path(__file__).resolve().parents[1] / "arena" / "maintenance" / "readme_refresh.py"
    spec = importlib.util.spec_from_file_location("readme_refresh", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Missing publisher loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="publisher")
def publisher_fixture(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test-only-placeholder")
    monkeypatch.setenv("GITHUB_REPOSITORY", "IvanSkainet/arena-agent")
    return load_publisher()


def test_missing_credential_stops_before_subprocess(monkeypatch):
    publisher = load_publisher()
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(publisher, "run", lambda *a, **k: pytest.fail("Subprocess before credential check"))
    with pytest.raises(SystemExit, match="README_TRAFFIC_TOKEN"):
        publisher.main()


def test_pending_review_is_not_invalidated(publisher, monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return '[{"number":123,"headRefName":"automation/readme-metrics-existing","isCrossRepository":false}]' if args[0] == "gh" else ""

    monkeypatch.setattr(publisher, "run", fake_run)
    publisher.main()
    assert len(calls) == 2  # nosec B101 -- status and pending-PR query only.


def test_pr_base_head_and_push_target_are_exact(publisher, monkeypatch):
    calls = []
    branch = "automation/readme-metrics-known"

    def fake_run(*args, env=None):
        calls.append(args)
        if "push" in args:
            if env is None:
                pytest.fail("Push lost its credential environment")
            assert env["GH_TOKEN"] == "test-only-placeholder"  # nosec B101 -- credential propagation.
            assert "GIT_ASKPASS" in env  # nosec B101 -- helper contract.
        return ""

    monkeypatch.setattr(publisher, "run", fake_run)
    publisher._publish("IvanSkainet/arena-agent", branch, publisher._git_environment())
    push = next(call for call in calls if "push" in call)
    create = next(call for call in calls if call[:3] == ("gh", "pr", "create"))
    assert push[-1] == "HEAD:refs/heads/" + branch  # nosec B101 -- no master push.
    assert create[create.index("--base") + 1] == "master"  # nosec B101 -- exact base.
    assert create[create.index("--head") + 1] == branch  # nosec B101 -- exact head.
    assert "--force" not in push  # nosec B101 -- protected publication.


def test_retries_choose_fresh_branch_names(publisher, monkeypatch):
    branches = []
    monkeypatch.setattr(publisher, "run", lambda *a, **k: "")
    monkeypatch.setattr(publisher, "_pending_review", lambda repo: False)
    monkeypatch.setattr(publisher, "_render_branch", lambda repo, branch, env: branches.append(branch))
    publisher.main()
    publisher.main()
    assert len(set(branches)) == 2  # nosec B101 -- no retained-tip collision.


def test_no_change_does_not_publish(publisher, monkeypatch):
    monkeypatch.setattr(publisher, "run", lambda *a, **k: "")
    monkeypatch.setattr(publisher, "_pending_review", lambda repo: False)
    monkeypatch.setattr(publisher, "_render_branch", lambda *a: False)
    monkeypatch.setattr(publisher, "_publish", lambda *a: pytest.fail("Unexpected publish"))
    publisher.main()


def test_failure_diagnostics_redact_credentials(publisher, monkeypatch, capsys):
    result = SimpleNamespace(returncode=1, stdout="", stderr="401 test-only-placeholder")
    monkeypatch.setattr(publisher.subprocess, "run", lambda *a, **k: result)
    with pytest.raises(publisher.subprocess.CalledProcessError):
        publisher.run("gh", "pr", "list")
    output = capsys.readouterr().err
    assert "401" in output  # nosec B101 -- actionable failure.
    assert "test-only-placeholder" not in output  # nosec B101 -- no secret leakage.


def test_large_pending_listing_fails_closed(publisher, monkeypatch):
    import json

    monkeypatch.setattr(publisher, "run", lambda *a, **k: json.dumps([{}] * 1000))
    with pytest.raises(SystemExit, match="incomplete"):
        publisher._pending_review("IvanSkainet/arena-agent")


def test_real_git_askpass_with_placeholder_only(publisher):
    import subprocess  # nosec B404 -- local credential-helper integration, no network.

    result = subprocess.run(  # nosec B603,B607 -- fixed git credential fill, no remote request.
        ["git", "-c", "credential.helper=", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n", env=publisher._git_environment(),
        capture_output=True, text=True, timeout=git_timeout(), check=True,
    )
    assert "username=x-access-token" in result.stdout  # nosec B101 -- placeholder identity.
    assert "password=test-only-placeholder" in result.stdout  # nosec B101 -- helper propagation, never real secret.


def test_fork_cannot_suppress_own_refresh(publisher, monkeypatch):
    payload = '[{"headRefName":"automation/readme-metrics-fork","isCrossRepository":true}]'
    monkeypatch.setattr(publisher, "run", lambda *a, **k: payload)
    assert not publisher._pending_review("IvanSkainet/arena-agent")  # nosec B101 -- fork is not an owned review.

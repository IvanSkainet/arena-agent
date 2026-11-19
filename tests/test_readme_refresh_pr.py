"""Traffic refresh never writes the protected base or invalidates pending review."""
import importlib.util
from pathlib import Path

import pytest


def load_publisher():
    path = Path(__file__).resolve().parents[1] / "scripts" / "refresh_readme_pr.py"
    spec = importlib.util.spec_from_file_location("refresh_readme_pr", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Missing publisher loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_credential_stops_before_subprocess(monkeypatch):
    publisher = load_publisher()
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="README_TRAFFIC_TOKEN"):
        publisher.main()


@pytest.mark.parametrize("pending", [True, False])
def test_protected_pr_publication_contract(monkeypatch, pending):
    publisher = load_publisher()
    monkeypatch.setenv("GH_TOKEN", "test-only-placeholder")
    monkeypatch.setenv("GITHUB_REPOSITORY", "IvanSkainet/arena-agent")
    calls = []

    def fake_run(*args, env=None):
        calls.append(args)
        if args[:3] == ("gh", "pr", "list"):
            return '[{"number": 123}]' if pending else '[]'
        if args[:2] == ("git", "diff"):
            return "README changed"
        if "push" in args:
            assert env is not None  # nosec B101 -- regression, not production guard.
            assert "GIT_ASKPASS" in env  # nosec B101 -- ephemeral helper required.
            assert Path(env["GIT_ASKPASS"]).is_file()  # nosec B101 -- helper lifetime.
        return ""

    monkeypatch.setattr(publisher, "run", fake_run)
    assert publisher.main() == 0  # nosec B101 -- pytest result.
    pushes = [call for call in calls if "push" in call]
    if pending:
        assert not pushes  # nosec B101 -- do not invalidate reviews.
        assert len(calls) == 2  # nosec B101 -- status plus PR lookup only.
    else:
        assert len(pushes) == 1  # nosec B101 -- one ordinary branch push.
        assert pushes[0][-1] == "HEAD:refs/heads/automation/readme-metrics"  # nosec B101 -- no master push.
        assert any(call[:3] == ("gh", "pr", "create") for call in calls)  # nosec B101 -- PR required.
        assert not any("--force" in call for call in calls)  # nosec B101 -- no force push.

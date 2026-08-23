"""v4.169.42 -- scheduled gitleaks scanned history and the allowlist did not.

The push job on 433f6df6 was green. The next night's `schedule` run
(#31676936942) scanned 1852 commits and reported 12 leaks. All twelve
were fixtures, an RFC 6455 example WebSocket nonce, or files that no
longer exist on HEAD. `.gitleaks.toml` only allowlisted the redaction
tests, so a blocking scanner that looks at history had never been
asked the question it is supposed to answer.

A detector that is green on push and red on schedule is the same shape
as a gate that never looks: the nightly run is the first time the
config meets the real input.

These tests pin the allowlist to those known false-positive paths, refuse
a blanket `tests/` exemption (that would hide a real secret in a new
test), and — when the gitleaks binary is present — sabotage both ways
against a throwaway git repo.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._git_budget import git_timeout

REPO_ROOT = Path(__file__).resolve().parents[1]
GITLEAKS_TOML = REPO_ROOT / ".gitleaks.toml"

# Paths that run #31676936942 named. Must stay allowlisted so the
# scheduled history scan stays honest about *new* secrets.
SCHEDULED_FALSE_POSITIVE_PATHS = (
    "tests/test_handlers_update_parity_v4_169_39.py",
    "tests/_mcp_description_fingerprint.json",
    "arena/browser/cdp_client/sync_browser.py",
    "scripts/cdp_browser_modules/sync_browser.py",
    "docs/AI_SYSTEM_PROMPT.md",
    "stress-test-v2.sh",
    "memory/facts.jsonl",
    "scripts/cdp_browser.py",
    "tools/superpowers/tests/brainstorm-server/ws-protocol.test.js",
)

RFC6455_EXAMPLE_KEY = "dGhlIHNhbXBsZSBub25jZQ=="


def _toml_text() -> str:
    return GITLEAKS_TOML.read_text(encoding="utf-8")


def test_gitleaks_config_exists_and_extends_defaults() -> None:
    text = _toml_text()
    assert "useDefault = true" in text
    assert "[allowlist]" in text


def test_scheduled_false_positive_paths_are_allowlisted() -> None:
    text = _toml_text()
    missing = [path for path in SCHEDULED_FALSE_POSITIVE_PATHS if path.replace(".", r"\.") not in text]
    assert missing == [], (
        "scheduled gitleaks named these paths and the allowlist no longer "
        f"covers them: {missing}"
    )


def test_allowlist_is_not_a_blanket_tests_star() -> None:
    """A `tests/` exemption would hide a real secret in any new test."""
    text = _toml_text()
    assert "'''tests/'''" not in text
    assert "'''tests/.*'''" not in text
    assert "'''tests/\\.*'''" not in text


def test_rfc6455_example_websocket_key_is_allowlisted() -> None:
    assert RFC6455_EXAMPLE_KEY in _toml_text()


def test_update_token_fixture_is_concatenated_not_inlined() -> None:
    """AGENTS.md: never inline a credential-shape string as a fixture."""
    src = (REPO_ROOT / "tests" / "test_handlers_update_parity_v4_169_39.py").read_text(
        encoding="utf-8"
    )
    glued = "ghp" + "_" + "secret123"
    assert glued not in src
    assert '"ghp"' in src and '"_"' in src


def _gitleaks() -> str | None:
    return shutil.which("gitleaks")


def _run_gitleaks(cwd: Path) -> subprocess.CompletedProcess[str]:
    exe = _gitleaks()
    assert exe is not None
    return subprocess.run(
        [
            exe,
            "detect",
            "--redact",
            "--exit-code=1",
            "--config",
            str(GITLEAKS_TOML),
            "--source",
            str(cwd),
            "--no-banner",
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        env=os.environ.copy(),
    )


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, timeout=git_timeout())
    subprocess.run(["git", "config", "user.name", "gate"], cwd=root, check=True, timeout=git_timeout())
    subprocess.run(["git", "config", "user.email", "gate@example.test"], cwd=root, check=True, timeout=git_timeout())
    subprocess.run(["git", "config", "core.fileMode", "false"], cwd=root, check=True, timeout=git_timeout())


def _commit(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=root, check=True, timeout=git_timeout())
    subprocess.run(["git", "commit", "-q", "-m", f"add {rel}"], cwd=root, check=True, timeout=git_timeout())


@pytest.mark.skipif(_gitleaks() is None, reason="gitleaks binary not on PATH")
def test_gitleaks_still_catches_a_real_token_outside_the_allowlist(tmp_path: Path) -> None:
    """Sabotage: a GitHub-shaped token in a new file must still fail."""
    repo = tmp_path / "leak"
    repo.mkdir()
    _init_git_repo(repo)
    # Mixed alphabet: an all-A suffix is below gitleaks' entropy floor.
    token = "ghp" + "_" + "1234567890abcdefghijklmnopqrstuvwxYZ"
    _commit(repo, "arena/new_module.py", f"TOKEN = {token!r}\n")
    result = _run_gitleaks(repo)
    assert result.returncode == 1, (
        "gitleaks accepted a planted token outside the allowlist:\n"
        f"{result.stdout}\n{result.stderr}"
    )


@pytest.mark.skipif(_gitleaks() is None, reason="gitleaks binary not on PATH")
def test_gitleaks_does_not_flag_the_rfc_example_key(tmp_path: Path) -> None:
    """Reverse sabotage: the RFC 6455 example nonce is not a secret."""
    repo = tmp_path / "rfc"
    repo.mkdir()
    _init_git_repo(repo)
    _commit(
        repo,
        "arena/browser/cdp_client/sync_browser.py",
        f'handshake = "Sec-WebSocket-Key: {RFC6455_EXAMPLE_KEY}\\r\\n"\n',
    )
    result = _run_gitleaks(repo)
    assert result.returncode == 0, (
        "RFC example key was treated as a leak again:\n"
        f"{result.stdout}\n{result.stderr}"
    )


@pytest.mark.skipif(_gitleaks() is None, reason="gitleaks binary not on PATH")
def test_gitleaks_is_clean_on_this_repository() -> None:
    exe = _gitleaks()
    assert exe is not None
    result = subprocess.run(
        [
            exe,
            "detect",
            "--redact",
            "--exit-code=1",
            "--config",
            str(GITLEAKS_TOML),
            "--no-banner",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "gitleaks is red on the real tree after the allowlist fix:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_allowlist_does_not_globally_permit_github_pats() -> None:
    """A global GitHub-PAT regex would hide a real token anywhere in history."""
    text = _toml_text()
    # The old (dangerous) allowlist entry, assembled so this file stays clean.
    forbidden = "ghp" + "_" + "[a-zA-Z0-9]{36}"
    assert forbidden not in text

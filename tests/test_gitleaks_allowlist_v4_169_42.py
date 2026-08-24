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

These tests pinned the allowlist to those paths -- and that pinning was
itself the defect, found in #177. A `paths` entry disables *every*
gitleaks rule for the file, not just the rule that fired, and four of
the nine paths were live source. A planted GitHub PAT in them produced
zero findings from all three scanners: gitleaks skipped the file,
trufflehog runs --only-verified, and semgrep's packs have no plain
github-pat rule. This gate could not see that, because its own sabotage
planted the token in a file that was never allowlisted.

The exemptions are now rule- and value-scoped, and the sabotage below
plants into the formerly-allowlisted paths, which is where the hole was.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._git_budget import git_timeout

try:  # Python >= 3.11
    import tomllib
except ModuleNotFoundError:  # 3.10 is still in the CI matrix
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
GITLEAKS_TOML = REPO_ROOT / ".gitleaks.toml"

# Paths run #31676936942 named. These must NOT be blanket-allowlisted:
# four are live source, and a path entry blinds the file to every rule.
# Kept as the sabotage corpus -- a planted secret in any of them must be
# caught.
FORMERLY_ALLOWLISTED_PATHS = (
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


def test_no_live_source_file_is_blanket_allowlisted() -> None:
    """A `paths` entry disables every rule for that file (#177).

    Four of the original nine paths were live source on HEAD, and the
    config comment claimed they no longer existed. A real credential in
    any of them was ignored by all three scanners.
    """
    cfg = tomllib.loads(_toml_text())
    # Only the top-level allowlist blinds a file to every rule. A
    # [[rules]] + [rules.allowlist] entry exempts one rule and is fine,
    # so match on structure rather than on the text of the file.
    blanket = (cfg.get("allowlist") or {}).get("paths") or []
    still_exempt = [
        path
        for path in FORMERLY_ALLOWLISTED_PATHS
        if (REPO_ROOT / path).exists()
        and any(path.replace(".", r"\.") == entry for entry in blanket)
    ]
    assert still_exempt == [], (
        "these files exist on HEAD and are blanket-allowlisted, so no "
        f"gitleaks rule applies to them: {still_exempt}"
    )


def test_the_top_level_allowlist_has_no_paths_key() -> None:
    """Scope exemptions to a rule or a value, never to a whole file."""
    cfg = tomllib.loads(_toml_text())
    paths = (cfg.get("allowlist") or {}).get("paths")
    assert not paths, (
        "top-level allowlist paths blind those files to every rule; use "
        f"[[rules]] + [rules.allowlist] or a value regex instead: {paths}"
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


def _planted_token() -> str:
    """A PAT-shaped string gitleaks will actually detect.

    The previous fixture was the `ghp_` prefix followed by a sequential
    run of digits and the alphabet, whose entropy is below the github-pat
    rule's floor -- gitleaks reports nothing for it. Spelling that literal
    out here made gitleaks flag this file, the same self-catching trap the
    stub-server gate hit in #176: a gate must not quote the pattern it
    hunts. Every sabotage in this
    module was therefore asserting against a token the scanner ignores,
    on top of never running at all. Generated from a fixed seed so the
    value is deterministic but not a recognisable literal.
    """
    import random
    import string

    rng = random.Random(20260824)
    body = "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(36))
    return "ghp" + "_" + body


def _gitleaks() -> str | None:
    """Locate the binary, including the /tmp/tools dir CI and local runs use.

    Every executable test in this module was skipping -- `shutil.which`
    alone finds nothing when the tool is installed to a target dir, so
    the module was three green skips: exactly the "green != working"
    failure the gate exists to prevent.
    """
    found = shutil.which("gitleaks")
    if found:
        return found
    for candidate in (Path("/tmp/tools/bin/gitleaks"), Path("/usr/local/bin/gitleaks")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


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
    token = _planted_token()
    _commit(repo, "arena/new_module.py", f"TOKEN = {token!r}\n")
    result = _run_gitleaks(repo)
    assert result.returncode == 1, (
        "gitleaks accepted a planted token outside the allowlist:\n"
        f"{result.stdout}\n{result.stderr}"
    )


@pytest.mark.skipif(_gitleaks() is None, reason="gitleaks binary not on PATH")
@pytest.mark.parametrize("rel", FORMERLY_ALLOWLISTED_PATHS)
def test_a_planted_token_in_a_formerly_allowlisted_path_is_caught(
    rel: str, tmp_path: Path
) -> None:
    """The hole #177 found: these paths were exempt from *every* rule.

    The old sabotage planted into `arena/new_module.py`, which was never
    allowlisted, so it passed while a PAT in these four files was
    invisible to gitleaks, trufflehog (--only-verified) and semgrep
    alike.
    """
    repo = tmp_path / "planted"
    repo.mkdir()
    _init_git_repo(repo)
    token = _planted_token()
    _commit(repo, rel, f"TOKEN = {token!r}\n")
    result = _run_gitleaks(repo)
    assert result.returncode == 1, (
        f"a planted token in {rel} was not reported; the allowlist is "
        f"blinding the file to every rule again:\n{result.stdout}\n{result.stderr}"
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


@pytest.mark.skipif(_gitleaks() is None, reason="gitleaks binary not on PATH")
def test_this_gate_does_not_trip_itself(tmp_path: Path) -> None:
    """A gate that quotes the pattern it hunts fails on its own source.

    The first version of this module spelled the old fixture token out in
    a docstring, and the `gitleaks` CI job went red on this very file --
    the same self-catching trap `tests/test_stub_servers_bind_once_175.py`
    hit in #176. Assert it directly rather than relying on the full-repo
    scan to notice.
    """
    repo = tmp_path / "selfscan"
    repo.mkdir()
    _init_git_repo(repo)
    _commit(
        repo,
        Path(__file__).name,
        Path(__file__).read_text(encoding="utf-8"),
    )
    result = _run_gitleaks(repo)
    assert result.returncode == 0, (
        "this gate's own source trips gitleaks; do not quote credential "
        f"shapes here:\n{result.stdout}\n{result.stderr}"
    )

"""v4.42.0 tests for the expanded sandbox sensitivity checks.

Covers three new pieces of behaviour:

1. ``validate_download_target`` refuses sensitive files
   (previously it only checked home-scope, letting an authed
   caller pull ``token.txt`` via ``/v1/download``).
2. ``validate_upload_target`` refuses sensitive files
   (previously it only checked bridge_py, letting an authed
   caller replace ``token.txt`` via ``/v1/upload``).
3. The sensitive check now covers ``.ssh/*``, ``.aws/*``,
   ``.gnupg/*``, ``.docker/*``, ``.kube/*``, browser profiles,
   and shell history -- not just bare basenames.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from arena.files.sandbox import (
    SENSITIVE_DIR_PREFIXES,
    SENSITIVE_FILE_BASENAMES,
    _path_hits_sensitive_prefix,
    _sensitivity_error,
    validate_create_target,
    validate_download_target,
    validate_edit_target,
    validate_upload_target,
    validate_view_target,
)


@pytest.fixture
def sandbox(tmp_path):
    """Build a fake home + writable root pair. The bridge_py
    argument is a dummy file just so the identity check has
    something to compare against."""
    home = tmp_path / "home"
    home.mkdir()
    root = home / "workspace"
    root.mkdir()
    bridge_py = tmp_path / "bridge.py"
    bridge_py.write_text("# fake")
    # Standard credential files that must be blocked.
    (home / "token.txt").write_text("secret")
    (home / ".env").write_text("SECRET=1")
    ssh = home / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text("key")
    (ssh / "authorized_keys").write_text("ssh-ed25519 AAAA...")
    (ssh / "known_hosts").write_text("github.com ...")
    aws = home / ".aws"
    aws.mkdir()
    (aws / "credentials").write_text("[default]\naws_key=...")
    (aws / "config").write_text("[default]\nregion=eu-north-1")
    gnupg = home / ".gnupg"
    gnupg.mkdir()
    (gnupg / "private-keys-v1.d").mkdir()
    (gnupg / "private-keys-v1.d" / "abc.key").write_text("secret")
    (home / ".bash_history").write_text("export TOKEN=leaked\n")
    (home / ".config" / "gh").mkdir(parents=True)
    (home / ".config" / "gh" / "hosts.yml").write_text("github.com:\n  oauth_token: ghp_leaked")
    (home / ".config" / "htop").mkdir()
    (home / ".config" / "htop" / "htoprc").write_text("# not sensitive")
    return {"home": home, "root": root, "bridge_py": bridge_py}


# ---------------------------------------------------------------------------
# Prefix-scan helper
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("relpath,expected_prefix", [
    (".ssh/id_ed25519", ".ssh"),
    (".ssh/authorized_keys", ".ssh"),
    (".aws/credentials", ".aws"),
    (".aws/config", ".aws"),
    (".gnupg/private-keys-v1.d/abc.key", ".gnupg"),
    (".config/gh/hosts.yml", ".config/gh"),
    # Sensitive dir NAME appearing deeper in the tree -- still blocked.
    ("projects/rogue/.ssh/authorized_keys", ".ssh"),
])
def test_prefix_scan_hits_sensitive_paths(sandbox, relpath, expected_prefix):
    home = sandbox["home"]
    # Create the file so resolve() has something to work with.
    target = home / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x")
    hit = _path_hits_sensitive_prefix(target, home)
    assert hit == expected_prefix, f"expected {expected_prefix!r}, got {hit!r}"


@pytest.mark.parametrize("relpath", [
    "workspace/project/main.py",
    "docs/notes.md",
    ".config/htop/htoprc",  # multi-segment prefix should NOT match .config alone
    ".config/nvim/init.lua",
    "sshkey_backup.txt",    # basename resembles but isn't
])
def test_prefix_scan_clears_ordinary_files(sandbox, relpath):
    home = sandbox["home"]
    target = home / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x")
    assert _path_hits_sensitive_prefix(target, home) is None


# ---------------------------------------------------------------------------
# validate_download_target -- the pre-v4.42.0 gap
# ---------------------------------------------------------------------------
def test_download_refuses_token_txt(sandbox):
    """The critical fix: pre-v4.42.0 an authed caller could pull
    the master bearer via /v1/download?path=token.txt. Now refused."""
    home, root = sandbox["home"], sandbox["root"]
    _, err, status = validate_download_target("token.txt", root=home, home=home)
    assert status == 403
    assert "download" in err.lower() and "token.txt" in err


def test_download_refuses_ssh_private_key(sandbox):
    home, root = sandbox["home"], sandbox["root"]
    _, err, status = validate_download_target(
        ".ssh/id_ed25519", root=home, home=home)
    assert status == 403
    assert "download" in err.lower()


def test_download_refuses_sensitive_even_when_absent(sandbox):
    """The sensitivity check must run BEFORE the exists check --
    otherwise an attacker could distinguish "file exists but
    blocked" (403) from "file does not exist" (404) and use
    that side channel to enumerate credential material on the
    bridge host."""
    home = sandbox["home"]
    # Delete the file so it doesn't exist.
    (home / ".aws" / "credentials").unlink()
    _, err, status = validate_download_target(
        ".aws/credentials", root=home, home=home)
    assert status == 403, (
        f"expected 403 even though file was removed; got {status} {err!r}. "
        "The sensitivity check must precede the existence check to close the "
        "exists-vs-blocked side channel."
    )


def test_download_refuses_aws_credentials(sandbox):
    home = sandbox["home"]
    _, err, status = validate_download_target(
        ".aws/credentials", root=home, home=home)
    assert status == 403


def test_download_refuses_git_credentials(sandbox):
    home = sandbox["home"]
    (home / ".git-credentials").write_text("https://user:pass@github.com")
    _, err, status = validate_download_target(
        ".git-credentials", root=home, home=home)
    assert status == 403


def test_download_refuses_shell_history(sandbox):
    home = sandbox["home"]
    _, err, status = validate_download_target(
        ".bash_history", root=home, home=home)
    assert status == 403


def test_download_allows_ordinary_workspace_file(sandbox):
    home, root = sandbox["home"], sandbox["root"]
    (root / "notes.md").write_text("hello")
    target, err, status = validate_download_target(
        str(root / "notes.md"), root=root, home=home)
    assert err is None
    assert status == 200


# ---------------------------------------------------------------------------
# validate_upload_target -- same story, other direction
# ---------------------------------------------------------------------------
def test_upload_refuses_token_txt(sandbox):
    """Symmetric fix: pre-v4.42.0 an authed caller could
    upload a replacement token.txt. Now refused."""
    home, root, bp = sandbox["home"], sandbox["root"], sandbox["bridge_py"]
    _, err, status = validate_upload_target(
        "token.txt", root=home, home=home, bridge_py=bp)
    assert status == 403
    assert "upload" in err.lower()


def test_upload_refuses_authorized_keys(sandbox):
    """Uploading an authorized_keys is a straight backdoor. Reject."""
    home, root, bp = sandbox["home"], sandbox["root"], sandbox["bridge_py"]
    _, err, status = validate_upload_target(
        ".ssh/authorized_keys", root=home, home=home, bridge_py=bp)
    assert status == 403


def test_upload_refuses_env_file(sandbox):
    home, root, bp = sandbox["home"], sandbox["root"], sandbox["bridge_py"]
    _, err, status = validate_upload_target(
        ".env", root=home, home=home, bridge_py=bp)
    assert status == 403


def test_upload_allows_ordinary_workspace_file(sandbox):
    home, root, bp = sandbox["home"], sandbox["root"], sandbox["bridge_py"]
    target, err, status = validate_upload_target(
        str(root / "new-file.txt"), root=root, home=home, bridge_py=bp)
    assert err is None
    assert status == 200


# ---------------------------------------------------------------------------
# view / edit / create -- confirm parity remains intact
# ---------------------------------------------------------------------------
def test_view_refuses_ssh_private_key(sandbox):
    home = sandbox["home"]
    _, err, status = validate_view_target(
        ".ssh/id_ed25519", root=home, home=home)
    assert status == 403


def test_edit_refuses_ssh_authorized_keys(sandbox):
    home, bp = sandbox["home"], sandbox["bridge_py"]
    _, err, status = validate_edit_target(
        ".ssh/authorized_keys", root=home, home=home, bridge_py=bp)
    assert status == 403


def test_create_refuses_new_file_under_ssh(sandbox):
    """A new file under a sensitive prefix is also blocked --
    creating ~/.ssh/rogue would let an attacker plant a helper
    script inside a directory the shell trusts."""
    home, bp = sandbox["home"], sandbox["bridge_py"]
    _, err, status = validate_create_target(
        ".ssh/rogue", root=home, home=home, bridge_py=bp)
    assert status == 403


def test_create_allows_ordinary_workspace_file(sandbox):
    home, root, bp = sandbox["home"], sandbox["root"], sandbox["bridge_py"]
    _, err, status = validate_create_target(
        str(root / "new.txt"), root=root, home=home, bridge_py=bp)
    assert err is None
    assert status == 200


# ---------------------------------------------------------------------------
# Basename list itself
# ---------------------------------------------------------------------------
def test_sensitive_basenames_include_credential_files():
    """Regression: keep the list from silently shrinking."""
    must = {"token.txt", ".env", "id_rsa", "id_ed25519", ".netrc",
            ".git-credentials", ".pypirc", ".npmrc",
            ".bash_history", ".zsh_history", ".python_history"}
    missing = must - SENSITIVE_FILE_BASENAMES
    assert not missing, f"expected in blocklist but absent: {missing}"


def test_sensitive_dir_prefixes_include_credential_dirs():
    must = {".ssh", ".aws", ".gnupg", ".docker", ".kube",
            ".config/gh", ".config/git",
            ".mozilla", ".config/google-chrome"}
    missing = must - SENSITIVE_DIR_PREFIXES
    assert not missing, f"expected prefix in blocklist but absent: {missing}"


# ---------------------------------------------------------------------------
# _sensitivity_error verb injection
# ---------------------------------------------------------------------------
def test_sensitivity_error_uses_verb(sandbox):
    home = sandbox["home"]
    tgt = home / "token.txt"
    err = _sensitivity_error(tgt, home, action="reading")
    assert err is not None
    msg, status = err
    assert status == 403
    assert msg.startswith("reading ")


def test_sensitivity_error_clear_for_ordinary_file(sandbox):
    home, root = sandbox["home"], sandbox["root"]
    tgt = root / "ok.txt"
    tgt.write_text("hello")
    assert _sensitivity_error(tgt, home, action="reading") is None

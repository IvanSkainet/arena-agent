"""v4.43.0 tests that the skills installer refuses ``file://``
URLs pointing at sensitive files (would otherwise let an
authed admin agent stage the master token or SSH keys into
the skills tempfile).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from arena.skills.install import install_skill


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Pretend $HOME is a fresh tmp dir so we can plant a fake
    sensitive file at ``~/token.txt`` without touching a real
    user home. All installer probes route through Path.home()
    which honours the HOME env var on POSIX."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_file_uri_refuses_token_txt(home, tmp_path):
    """The critical fix: file:///~/token.txt cannot be staged
    as a skill zip. Otherwise the master bearer token would
    end up in the skills' tmp directory."""
    # Name the source with a .zip suffix so the installer routes
    # through the local-file branch we're testing (the non-.zip
    # branch is a completely different code path that goes to
    # git clone).
    (home / "token.txt").write_text("MASTER_TOKEN_ABC")
    skills_dir = home / "skills"
    # Use a symlink so we hit the sensitive-basename check on
    # the resolved target -- the alias itself ends in .zip so
    # the .zip branch is taken.
    alias = home / "leak.zip"
    alias.symlink_to(home / "token.txt")
    result = install_skill(
        "test_leak", f"file://{alias}",
        skills_dir=skills_dir,
    )
    assert result["ok"] is False, (
        "install_skill must refuse file:// URLs pointing at "
        "sensitive files"
    )
    assert "not allowed" in result["error"].lower() or \
           "sensitive" in result["error"].lower(), (
        f"unexpected error: {result['error']!r}"
    )


def test_file_uri_refuses_ssh_private_key(home):
    ssh = home / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text("SSH_PRIVATE_KEY")
    # Same trick as above -- symlink into the sensitive path
    # with a .zip suffix so we hit the local-file branch.
    alias = home / "leak.zip"
    alias.symlink_to(ssh / "id_ed25519")
    result = install_skill(
        "leak_ssh", f"file://{alias}",
        skills_dir=home / "skills",
    )
    assert result["ok"] is False
    assert "not allowed" in result["error"].lower() or \
           "sensitive" in result["error"].lower()


def test_bare_path_also_refuses_sensitive(home):
    """No ``file://`` prefix -- just an absolute path with the
    .zip suffix so the local-file branch fires."""
    (home / "token.txt").write_text("SECRET")
    alias = home / "leak.zip"
    alias.symlink_to(home / "token.txt")
    result = install_skill(
        "leak", str(alias),
        skills_dir=home / "skills",
    )
    assert result["ok"] is False


def test_file_uri_outside_home_permitted(home, tmp_path):
    """Paths OUTSIDE $HOME (mounted volume, /data/, /opt/, ...)
    are allowed without the sensitivity check. Rationale: the
    blocklist is meant to protect the user's private credential
    space; paths on external volumes are outside that scope, and
    the zip-slip / zip-bomb guard still fires in
    safe_extract_zip. Regression test: pre-v4.43.0 there was no
    scope check at all, and imposing "must live under HOME" as
    part of this hardening pass would break every legitimate
    admin who keeps skills on a data volume."""
    import zipfile
    external = tmp_path.parent / "elsewhere.zip"
    with zipfile.ZipFile(external, "w") as zf:
        zf.writestr("some-skill/hi.txt", "hello")
    result = install_skill(
        "external_ok", f"file://{external}",
        skills_dir=home / "skills",
    )
    # We don't assert ok=True (downstream chmod/git may still
    # complain in the harness), but we DO assert that the
    # rejection wasn't a "not allowed" from our sensitivity
    # check.
    if not result["ok"]:
        assert "not allowed" not in result["error"].lower()


def test_file_uri_accepts_ordinary_zip_in_home(home):
    """Positive control: a legitimate ~/some.zip installs fine
    (the sensitivity check does not over-block ordinary files)."""
    import zipfile
    z = home / "ok.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("ok-skill/hello.txt", "hi")
    result = install_skill(
        "ok_skill", f"file://{z}",
        skills_dir=home / "skills",
    )
    # We only assert we did NOT get a sandbox-rejection; downstream
    # steps (git, chmod, ...) may still complain about other things.
    if not result["ok"]:
        assert "not allowed" not in result["error"].lower()
        assert "must live" not in result["error"].lower()

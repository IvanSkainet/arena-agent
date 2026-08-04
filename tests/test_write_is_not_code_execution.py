"""Writing a file must not be a way to run code later.

Continuing the coverage-as-a-search pass: after ``arena/exec``, the next
lowest-covered code that can act on the machine was ``arena/files``. The
path-traversal defences turned out to be genuinely strong -- probed against a
live bridge, absolute paths outside root, ``../`` climbs, URL-encoded and
double-encoded traversal, and even symlinks *inside* root pointing outside it
were all refused. The sensitivity lists correctly protected ``token.txt``,
``.ssh/``, ``.aws/``, ``.gitconfig`` and shell history.

What they did not protect was the other half of the threat model. Those lists
answer "what must not leak". Nobody had asked "what must not be replaced":

    POST /v1/upload?path=/home/user/.bashrc   ->  200 OK

That is not a file disclosure. The next shell the operator opens executes the
attacker's content, with no privilege escalation anywhere in the chain. It
was observed for real during the probe -- the sandbox's own logs printed
``/home/user/.bashrc: line 1: PWNED: command not found`` on the next command,
because the poisoned file really was sourced.

``.ssh/authorized_keys`` was already refused. ``.bashrc``, ``.bash_profile``,
``.profile``, ``.zshrc``, ``~/.config/autostart/*.desktop`` and anything on
PATH under ``~/.local/bin`` were not.

The fix is a separate write-only list rather than an addition to the existing
ones, because the two questions have different answers: reading shell config
is legitimate agent behaviour and stays allowed. Only ``uploading``,
``editing`` and ``creating`` consult it; ``downloading`` and ``viewing`` do
not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from arena.files import sandbox as S  # noqa: E402

# Every one of these was writable before the fix.
EXECUTES_ON_WRITE = [
    ".bashrc",
    ".bash_profile",
    ".profile",
    ".zshrc",
    ".zshenv",
    ".vimrc",
    ".tmux.conf",
    ".config/autostart/evil.desktop",
    ".config/systemd/user/evil.service",
    ".config/fish/config.fish",
    ".local/bin/agentctl",
    "bin/helper",
    "projects/.bashrc",          # depth is not a loophole
]

# Ordinary files an agent must still be able to write.
ORDINARY = [
    "notes.txt",
    "src/main.py",
    "data/report.json",
    "bashrc_notes.md",           # name merely *contains* a blocked word
    "docs/.bashrc.md",           # different basename
]


@pytest.fixture
def home(tmp_path):
    (tmp_path / ".config" / "autostart").mkdir(parents=True)
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    return tmp_path


@pytest.mark.parametrize("rel", EXECUTES_ON_WRITE)
def test_upload_refuses_paths_that_execute_later(home, rel):
    target = home / rel
    result, err, status = S.validate_upload_target(
        str(target), root=home, home=home, bridge_py=home / "unified_bridge.py")
    assert result is None and status == 403, (
        f"upload to {rel} was allowed; writing it is code execution on the "
        f"operator's next login (got status={status})")
    assert "not allowed" in (err or "")


@pytest.mark.parametrize("rel", EXECUTES_ON_WRITE)
def test_edit_and_create_refuse_them_too(home, rel):
    """Upload is not the only way in -- fs.edit and fs.create write as well."""
    target = home / rel
    for name, fn in (("edit", S.validate_edit_target),
                     ("create", S.validate_create_target)):
        result, err, status = fn(str(target), root=home, home=home,
                                 bridge_py=home / "unified_bridge.py")
        assert result is None and status == 403, (
            f"{name} to {rel} was allowed (status={status}); closing only "
            "upload would leave the same code-execution path open")


@pytest.mark.parametrize("rel", [".bashrc", ".zshrc", ".config/autostart/x.desktop"])
def test_reading_shell_config_is_still_allowed(home, rel):
    """A fix that blocked reads would break legitimate inspection for nothing."""
    target = home / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("export EXAMPLE=1\n", encoding="utf-8")

    for name, fn in (("download", S.validate_download_target),
                     ("view", S.validate_view_target)):
        result, err, status = fn(str(target), root=home, home=home)
        assert result is not None, (
            f"{name} of {rel} was refused ({err}); reading shell config is "
            "not the attack -- writing it is")


@pytest.mark.parametrize("rel", ORDINARY)
def test_ordinary_files_are_still_writable(home, rel):
    """A rule that refuses everything would make the tests above vacuous."""
    target = home / rel
    result, err, status = S.validate_upload_target(
        str(target), root=home, home=home, bridge_py=home / "unified_bridge.py")
    assert result is not None, f"upload to ordinary path {rel} was refused: {err}"


def test_secrets_are_still_refused(home):
    """The pre-existing protections must survive the new list."""
    for rel in ("token.txt", ".ssh/authorized_keys", ".aws/credentials",
                ".gitconfig", ".bash_history"):
        target = home / rel
        result, _err, status = S.validate_upload_target(
            str(target), root=home, home=home, bridge_py=home / "unified_bridge.py")
        assert result is None and status == 403, f"{rel} became writable"


def test_the_rule_is_write_only_by_construction():
    """Guard the design, not just today's behaviour."""
    src = (REPO / "arena" / "files" / "sandbox.py").read_text(encoding="utf-8")
    for verb in ("uploading", "editing", "creating"):
        assert f'_execution_on_write_error(target_path, home, action="{verb}")' in src, (
            f"the {verb} validator no longer consults the execution-on-write list")
    for verb in ("downloading", "viewing"):
        assert f'_execution_on_write_error(target_path, home, action="{verb}")' not in src, (
            f"{verb} must not be blocked: reading shell config is legitimate")

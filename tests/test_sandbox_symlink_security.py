"""Symlinks and case variants must not bypass file security policy."""
from __future__ import annotations

from pathlib import Path

import pytest

from arena.files.sandbox import (
    validate_create_target,
    validate_download_target,
    validate_edit_target,
    validate_upload_target,
    validate_view_target,
)


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")


@pytest.mark.parametrize("validator", [validate_view_target, validate_download_target])
def test_read_cannot_follow_benign_symlink_to_token(tmp_path, validator):
    secret = tmp_path / "token.txt"
    secret.write_text("secret", encoding="utf-8")
    alias = tmp_path / "ordinary.txt"
    _symlink(alias, secret)
    path, error, status = validator(str(alias), root=tmp_path, home=tmp_path)
    assert path is None and error and status == 403


@pytest.mark.parametrize("validator", [validate_upload_target, validate_edit_target])
def test_write_cannot_follow_benign_symlink_to_shell_profile(tmp_path, validator):
    startup = tmp_path / ".bashrc"
    startup.write_text("safe", encoding="utf-8")
    alias = tmp_path / "ordinary.txt"
    _symlink(alias, startup)
    path, error, status = validator(str(alias), root=tmp_path, home=tmp_path,
                                    bridge_py=tmp_path / "bridge.py")
    assert path is None and error and status == 403
    assert startup.read_text(encoding="utf-8") == "safe"


def test_case_variants_do_not_bypass_protection_on_case_insensitive_filesystems(tmp_path):
    # Blocking all case variants on every OS makes the policy portable.
    path, error, status = validate_create_target(str(tmp_path / "TOKEN.TXT"), root=tmp_path,
                                                 home=tmp_path, bridge_py=tmp_path / "bridge.py")
    assert path is None and error and status == 403
    sensitive_dir = tmp_path / ".SSH"
    sensitive_dir.mkdir()
    path, error, status = validate_create_target(str(sensitive_dir / "keys"), root=tmp_path,
                                                 home=tmp_path, bridge_py=tmp_path / "bridge.py")
    assert path is None and error and status == 403


def test_live_http_rejects_aliases_of_secrets_and_startup_scripts(tmp_path, monkeypatch):
    import asyncio
    from urllib.parse import quote

    from tests._live_bridge import auth_header, running_client

    workspace = tmp_path / "workspace"
    state = tmp_path / "state"
    workspace.mkdir()
    state.mkdir()
    monkeypatch.setenv("ARENA_AGENT_HOME", str(state))
    secret, startup = state / "token.txt", state / ".bashrc"
    secret.write_text("private-data", encoding="utf-8")
    startup.write_text("safe", encoding="utf-8")
    secret_alias, startup_alias = state / "ordinary.txt", state / "editable.txt"
    _symlink(secret_alias, secret)
    _symlink(startup_alias, startup)

    async def probe():
        async with running_client(workspace, "symlink-security") as client:
            headers = auth_header("symlink-security")
            view = await client.post("/v1/fs/view", json={"path": str(secret_alias)}, headers=headers)
            download = await client.get("/v1/download?path=" + quote(str(secret_alias)), headers=headers)
            upload = await client.post("/v1/upload?path=" + quote(str(startup_alias)),
                                       data=b"hostile", headers=headers)
            return view.status, download.status, upload.status

    assert asyncio.run(probe()) == (403, 403, 403)
    assert startup.read_text(encoding="utf-8") == "safe"

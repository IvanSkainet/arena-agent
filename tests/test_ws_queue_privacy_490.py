"""Queue initialization cannot chmod an unrelated symlink target."""
import os
import stat

import pytest

from arena.mcp.ws_push import _prepare_notify_queue


@pytest.mark.skipif(os.name == "nt", reason="POSIX O_NOFOLLOW and mode contract")
def test_queue_symlink_does_not_change_target_permissions(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    outside.chmod(0o644)
    queue = tmp_path / "private" / "queue"
    queue.parent.mkdir()
    queue.symlink_to(outside)
    with pytest.raises(OSError):
        _prepare_notify_queue(queue)
    assert stat.S_IMODE(outside.stat().st_mode) == 0o644
    assert outside.read_text() == "untouched"


@pytest.mark.skipif(os.name == "nt", reason="Windows privacy uses owner deployment ACLs")
def test_existing_notify_queue_is_private_without_losing_data(tmp_path):
    queue = tmp_path / "queue"
    queue.write_text("keep queued event\n")
    queue.chmod(0o666)
    _prepare_notify_queue(queue)
    assert stat.S_IMODE(queue.stat().st_mode) == 0o600
    assert queue.read_text() == "keep queued event\n"


@pytest.mark.skipif(os.name != "nt", reason="native Windows security descriptors")
def test_windows_queue_replaces_broad_explicit_and_inherited_grants(tmp_path):
    import json
    import subprocess

    queue = tmp_path / "private" / "queue"
    queue.parent.mkdir()
    queue.write_text("preserve queued event\n")
    subprocess.run(["icacls.exe", str(queue), "/grant", "*S-1-1-0:(F)"],
                   check=True, capture_output=True)
    _prepare_notify_queue(queue)
    script = (
        "$a=Get-Acl -LiteralPath $env:ARENA_ACL_TEST;"
        "@{Protected=$a.AreAccessRulesProtected;Access=@($a.Access|ForEach-Object {"
        "@{SID=$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value;"
        "Type=$_.AccessControlType.ToString();Inherited=$_.IsInherited}});"
        "User=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value}"
        "|ConvertTo-Json -Depth 5 -Compress")
    for path in (queue.parent, queue):
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env=dict(os.environ, ARENA_ACL_TEST=str(path)),
            capture_output=True, text=True, check=True)
        acl = json.loads(result.stdout)
        assert acl["Protected"] is True
        assert {entry["SID"] for entry in acl["Access"]} == {acl["User"], "S-1-5-18"}
        assert all(entry["Type"] == "Allow" and not entry["Inherited"] for entry in acl["Access"])
    assert queue.read_text() == "preserve queued event\n"

"""T74: complete immutable source inventory."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from arena.governance import benchmark_runner as bench


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX execute-bit identity")
def test_symlink_resolved_target_mode_is_part_of_source_identity(tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"same content")
    link = tmp_path / "entry"
    try:
        link.symlink_to(target.name)
    except OSError:
        pytest.skip("symlinks unavailable")
    before = bench.source_digest(tmp_path, link.name)
    target.chmod(target.stat().st_mode ^ 0o100)
    assert bench.source_digest(tmp_path, link.name) != before



def test_fingerprint_hashes_real_contents_and_uses_complete_git_inventory(tmp_path, monkeypatch):
    import hashlib

    (tmp_path / "tracked.py").write_bytes(b"tracked source\n")
    (tmp_path / "new file.py").write_bytes(b"new source\n")

    def listing(argv, **kwargs):
        assert argv == ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        assert kwargs == {"cwd": tmp_path, "capture_output": True, "check": True, "timeout": 30}
        return SimpleNamespace(stdout=b"tracked.py\0new file.py\0tracked.py\0")

    monkeypatch.setattr(bench.subprocess, "run", listing)
    assert bench.fingerprint(tmp_path) == {
        "new file.py": hashlib.sha256(json.dumps({"mode": (tmp_path / "new file.py").stat().st_mode & 0o7777}, sort_keys=True).encode() + b"\0new source\n").hexdigest(),
        "tracked.py": hashlib.sha256(json.dumps({"mode": (tmp_path / "tracked.py").stat().st_mode & 0o7777}, sort_keys=True).encode() + b"\0tracked source\n").hexdigest(),
    }



@pytest.mark.parametrize("kind", ["missing", "directory", "dangling"])
def test_git_inventory_cannot_silently_omit_an_entry(tmp_path, monkeypatch, kind):
    path = tmp_path / "entry"
    if kind == "directory":
        path.mkdir()
    elif kind == "dangling":
        try:
            path.symlink_to("absent")
        except OSError:
            pytest.skip("symlink creation unavailable")
    monkeypatch.setattr(bench.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=b"entry\0"))
    with pytest.raises((OSError, ValueError)):
        bench.fingerprint(tmp_path)



@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode identity")
def test_source_mode_change_invalidates_identical_content(tmp_path):
    path = tmp_path / "entry"
    path.write_bytes(b"same source")
    before = bench.source_digest(tmp_path, "entry")
    path.chmod(path.stat().st_mode ^ 0o100)
    assert bench.source_digest(tmp_path, "entry") != before



def test_symlink_target_change_invalidates_identical_content(tmp_path):
    for name in ["one", "two"]:
        (tmp_path / name).write_bytes(b"identical")
    link = tmp_path / "entry"
    try:
        link.symlink_to("one")
    except OSError:
        pytest.skip("symlink creation unavailable")
    before = bench.source_digest(tmp_path, "entry")
    link.unlink()
    link.symlink_to("two")
    assert bench.source_digest(tmp_path, "entry") != before



def test_source_digest_reports_external_links_and_nonfiles_precisely(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "directory").mkdir()
    with pytest.raises(ValueError, match="^source inventory contains a non-file entry$"):
        bench.source_digest(root, "directory")
    outside = tmp_path / "external"
    outside.write_text("fixture")
    try:
        (root / "link").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="^source symlink escapes the checkout$"):
        bench.source_digest(root, "link")



def test_source_digest_uses_reproducible_manifest_metadata_schema(tmp_path):
    import hashlib
    import stat

    target = tmp_path / "target"
    target.write_bytes(b"fixture content")
    link = tmp_path / "link"
    try:
        link.symlink_to(target.name)
    except OSError:
        pytest.skip("symlinks unavailable")
    # Independent schema oracle: manifest hashes must not drift across invocations.
    metadata = {"mode": stat.S_IMODE(link.lstat().st_mode), "target": "target",
                "target_mode": stat.S_IMODE(target.stat().st_mode)}
    expected = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode("utf-8")
                              + b"\0fixture content").hexdigest()
    assert bench.source_digest(tmp_path, "link") == expected

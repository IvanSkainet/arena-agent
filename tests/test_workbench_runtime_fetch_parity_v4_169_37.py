"""v4.169.37 -- arena.workbench.runtime_fetch parity tests (mutation-driven).

Fast, isolated tests for managed runtime downloads and safe extraction:
* `_CHUNK_SIZE_BYTES` pinned constant and multi-megabyte chunked hashing;
* `_verify_digest` failure messages (missing digest, sha256 mismatch, multi-colon prefix);
* `_safe_join_extract` destination containment validation and exact escape error message;
* `_extract_zip_safe` standalone directories, duplicate parents (exist_ok), and file content extraction;
* `_extract_tar_safe` standalone directories, non-regular members, None extractfile skips (continue not break), and shared parent files (exist_ok).
"""
from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.workbench.runtime_fetch as rf  # noqa: E402


# --------------------------------------------------------------------
# 1. _sha256
# --------------------------------------------------------------------
def test_sha256_constants_and_multi_megabyte(tmp_path):
    assert rf._CHUNK_SIZE_BYTES == 1024 * 1024
    f = tmp_path / "big_sample.bin"
    chunk = b"X" * (1024 * 1024)
    content = chunk + chunk + b"EXTRA"
    f.write_bytes(content)
    assert rf._sha256(f) == hashlib.sha256(content).hexdigest()


# --------------------------------------------------------------------
# 2. _verify_digest
# --------------------------------------------------------------------
def test_verify_digest_missing_exact_message(tmp_path):
    f = tmp_path / "archive.zip"
    f.write_bytes(b"payload")

    with pytest.raises(RuntimeError) as exc:
        rf._verify_digest(f, "", runtime="deno")
    assert str(exc.value) == (
        "refusing to install deno: the publisher did not provide a sha256 "
        "digest for archive.zip, so the download cannot be verified. Pass the "
        "expected digest explicitly if you have it from a trusted source."
    )


def test_verify_digest_mismatch_exact_message(tmp_path):
    f = tmp_path / "archive.zip"
    content = b"my-payload"
    f.write_bytes(content)
    real_hash = hashlib.sha256(content).hexdigest()

    with pytest.raises(RuntimeError) as exc:
        rf._verify_digest(f, "0" * 64, runtime="deno")
    assert str(exc.value) == f"sha256 mismatch for archive.zip: got {real_hash}, expected {'0' * 64}"


def test_verify_digest_multi_colon(tmp_path):
    f = tmp_path / "archive.zip"
    content = b"valid-content"
    f.write_bytes(content)
    real_hash = hashlib.sha256(content).hexdigest()

    # prefix:digest takes digest
    res = rf._verify_digest(f, f"sha256:{real_hash}", runtime="lua")
    assert res == real_hash


def test_verify_digest_extra_colons_in_prefix(tmp_path):
    f = tmp_path / "archive.zip"
    content = b"valid-content"
    f.write_bytes(content)
    real_hash = hashlib.sha256(content).hexdigest()

    with pytest.raises(RuntimeError) as exc:
        rf._verify_digest(f, f"sha256:extra:{real_hash}", runtime="lua")
    assert "sha256 mismatch" in str(exc.value)


# --------------------------------------------------------------------
# 3. _safe_join_extract
# --------------------------------------------------------------------
def test_safe_join_extract_valid(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    target = rf._safe_join_extract(dest, "bin/tool")
    assert target == dest / "bin" / "tool"


def test_safe_join_extract_escape_exact_message(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(RuntimeError) as exc:
        rf._safe_join_extract(dest, "../outside.txt")
    assert str(exc.value) == "archive member escapes destination: ../outside.txt"


# --------------------------------------------------------------------
# 4. _extract_zip_safe
# --------------------------------------------------------------------
def test_extract_zip_safe_dirs_and_files(tmp_path):
    dest = tmp_path / "dest_zip"
    dest.mkdir()

    archive = tmp_path / "test.zip"
    with zipfile.ZipFile(archive, "w") as z:
        # 1. Standalone deeply nested directory entry (tests parents=True)
        z.writestr("level1/level2/nested_empty_dir/", "")
        # Duplicate directory entry (tests exist_ok=True)
        z.writestr("level1/level2/nested_empty_dir/", "")
        # 2. Multiple files in the same directory (tests target.parent.mkdir exist_ok=True)
        z.writestr("shared_dir/file1.txt", "content 1")
        z.writestr("shared_dir/file2.txt", "content 2")
        # 3. File in nested path without explicit dir entry
        z.writestr("deep/sub/doc.md", "# Markdown")

    rf._extract_zip_safe(archive, dest)

    assert (dest / "level1" / "level2" / "nested_empty_dir").is_dir()
    assert (dest / "shared_dir" / "file1.txt").read_text(encoding="utf-8") == "content 1"
    assert (dest / "shared_dir" / "file2.txt").read_text(encoding="utf-8") == "content 2"
    assert (dest / "deep" / "sub" / "doc.md").read_text(encoding="utf-8") == "# Markdown"


# --------------------------------------------------------------------
# 5. _extract_tar_safe
# --------------------------------------------------------------------
def test_extract_tar_safe_dirs_and_files(tmp_path, monkeypatch):
    dest = tmp_path / "dest_tar"
    dest.mkdir()

    archive = tmp_path / "test.tar"
    with tarfile.open(archive, "w") as t:
        # 1. Standalone deeply nested directory member (tests parents=True)
        dir_info = tarfile.TarInfo("level1/level2/nested_empty_dir")
        dir_info.type = tarfile.DIRTYPE
        t.addfile(dir_info)

        # Duplicate directory member (tests exist_ok=True)
        dir_info2 = tarfile.TarInfo("level1/level2/nested_empty_dir")
        dir_info2.type = tarfile.DIRTYPE
        t.addfile(dir_info2)

        # 2. Non-regular member followed by regular files (tests continue, not break)
        fifo_info = tarfile.TarInfo("my_dir/fifo")
        fifo_info.type = tarfile.FIFOTYPE
        t.addfile(fifo_info)

        # 3. Two regular file members in the same parent (tests target.parent.mkdir exist_ok=True)
        file_data1 = b"tar payload 1"
        file_info1 = tarfile.TarInfo("deep_uncreated_parent/sub/file1.txt")
        file_info1.size = len(file_data1)
        t.addfile(file_info1, io.BytesIO(file_data1))

        # Member that will produce extractfile -> None, followed by regular file
        file_data_none = b"none data"
        file_info_none = tarfile.TarInfo("deep_uncreated_parent/sub/will_be_none.txt")
        file_info_none.size = len(file_data_none)
        t.addfile(file_info_none, io.BytesIO(file_data_none))

        file_data2 = b"tar payload 2"
        file_info2 = tarfile.TarInfo("deep_uncreated_parent/sub/file2.txt")
        file_info2.size = len(file_data2)
        t.addfile(file_info2, io.BytesIO(file_data2))

    orig_extractfile = tarfile.TarFile.extractfile

    def _spy_extractfile(self, member):
        if member.name.endswith("will_be_none.txt"):
            return None
        return orig_extractfile(self, member)

    monkeypatch.setattr(tarfile.TarFile, "extractfile", _spy_extractfile)

    rf._extract_tar_safe(archive, dest)

    assert (dest / "level1" / "level2" / "nested_empty_dir").is_dir()
    assert (dest / "deep_uncreated_parent" / "sub" / "file1.txt").read_bytes() == b"tar payload 1"
    assert (dest / "deep_uncreated_parent" / "sub" / "file2.txt").read_bytes() == b"tar payload 2"
    assert not (dest / "deep_uncreated_parent" / "sub" / "will_be_none.txt").exists()
    assert not (dest / "my_dir" / "fifo").exists()

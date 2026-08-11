"""v4.169.36 -- arena.admin.auto_update_fetch parity tests (mutation-driven).

Fast, isolated tests for release download and SHA-256 verification:
* `_err` dictionary schema;
* `_user_agent` delegation to `_USER_AGENT`;
* `_sha256_of` file hashing across multiple 1MB chunks;
* `_MAX_RELEASE_SIZE_BYTES` pinned constant and exact boundary enforcement (equal vs exceeded);
* `download_release` validation:
  - missing asset_url / asset_name;
  - dest_dir nested parent creation vs default temp directory creation;
  - SSRF refusal via `_validate_url`;
  - User-Agent header forwarding and timeout=60;
  - download exception formatting;
  - SHA256 digest parsing ('sha256:<hex>', 'sha256:sub:hash', uppercase, whitespace);
  - default allow_unverified=False enforcement;
  - absent digest allowed when allow_unverified=True (verified=False);
  - digest mismatch error with expected/got/path;
  - success response dictionary schema.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.admin.auto_update_fetch as auf  # noqa: E402
import arena.security_ssrf as ssrf  # noqa: E402


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)

    def read(self, size=-1) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# --------------------------------------------------------------------
# 0. Pinned Constants & Helpers
# --------------------------------------------------------------------
def test_max_release_size_and_chunk_constants_pinned():
    assert auf._MAX_RELEASE_SIZE_BYTES == 512 * 1024 * 1024
    assert auf._DOWNLOAD_CHUNK_SIZE_BYTES == 1024 * 1024


def test_err_schema():
    res = auf._err("something failed", extra_key="extra_val")
    assert res["ok"] is False
    assert res["ok"] != True  # noqa: E712
    assert res["error"] == "something failed"
    assert res["extra_key"] == "extra_val"
    assert res == {"ok": False, "error": "something failed", "extra_key": "extra_val"}


def test_download_release_two_colons_in_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(ssrf, "_validate_url", lambda url: None)
    content = b"PK\x03\x04test"

    monkeypatch.setattr(
        auf.urllib.request, "urlopen", lambda req, timeout=None: _FakeStreamResponse([content])
    )

    # With split(":", 1), "prefix:tag:val" takes "tag:val"
    res = auf.download_release(
        asset_url="https://github.com/test/valid.zip",
        asset_name="valid.zip",
        expected_sha256="prefix:tag:val",
        dest_dir=tmp_path,
    )
    assert res["expected"] == "tag:val"
    assert res["error"] == "sha256 mismatch after download"


def test_user_agent_returns_string():
    ua = auf._user_agent()
    assert isinstance(ua, str)
    assert len(ua) > 0


def test_sha256_of_multi_megabyte_file(tmp_path):
    # Create 2.5 MB file to exercise the 1MB chunk loop in _sha256_of
    f = tmp_path / "sample_large.bin"
    chunk = b"A" * (1024 * 1024)
    half_chunk = b"B" * (512 * 1024)
    content = chunk + chunk + half_chunk
    f.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest()
    assert auf._sha256_of(f) == expected_hash


# --------------------------------------------------------------------
# 1. download_release validation
# --------------------------------------------------------------------
@pytest.mark.parametrize(
    "url,name",
    [
        ("", "file.zip"),
        ("https://example.com/file.zip", ""),
        ("", ""),
    ],
)
def test_download_release_missing_args(url, name):
    res = auf.download_release(asset_url=url, asset_name=name)
    assert res == {"ok": False, "error": "asset_url and asset_name are required"}


def test_download_release_ssrf_rejected(monkeypatch):
    monkeypatch.setattr(
        ssrf, "_validate_url", lambda url: "private IP ranges prohibited"
    )
    res = auf.download_release(
        asset_url="http://192.168.1.1/evil.zip", asset_name="evil.zip"
    )
    assert res == {
        "ok": False,
        "error": "asset_url rejected: private IP ranges prohibited",
        "asset_url": "http://192.168.1.1/evil.zip",
    }


def test_download_release_size_cap_exact_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(ssrf, "_validate_url", lambda url: None)
    monkeypatch.setattr(auf, "_MAX_RELEASE_SIZE_BYTES", 100)

    # 1. Exact limit (100 bytes) -> MUST succeed
    content_100 = b"X" * 100
    content_hash_100 = hashlib.sha256(content_100).hexdigest()
    monkeypatch.setattr(
        auf.urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeStreamResponse([b"X" * 50, b"X" * 50]),
    )
    res_ok = auf.download_release(
        asset_url="https://github.com/test/exact.zip",
        asset_name="exact.zip",
        dest_dir=tmp_path / "exact",
        expected_sha256=content_hash_100,
    )
    assert res_ok["ok"] is True

    # 2. Exceeded limit (101 bytes) -> MUST fail
    monkeypatch.setattr(
        auf.urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeStreamResponse([b"X" * 50, b"X" * 51]),
    )
    res_exceeded = auf.download_release(
        asset_url="https://github.com/test/giant.zip",
        asset_name="giant.zip",
        dest_dir=tmp_path / "giant",
        allow_unverified=True,
    )
    assert res_exceeded == {
        "ok": False,
        "error": "release zip exceeded 512 MiB size cap",
        "asset_url": "https://github.com/test/giant.zip",
    }


def test_download_release_network_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(ssrf, "_validate_url", lambda url: None)

    def _fail_open(req, timeout=None):
        raise ConnectionResetError("connection dropped")

    monkeypatch.setattr(auf.urllib.request, "urlopen", _fail_open)

    res = auf.download_release(
        asset_url="https://github.com/test/release.zip",
        asset_name="release.zip",
        dest_dir=tmp_path,
    )
    assert res["ok"] is False
    assert res["error"] == "download failed: ConnectionResetError('connection dropped')"
    assert res["asset_url"] == "https://github.com/test/release.zip"


# --------------------------------------------------------------------
# 2. Digest verification branches
# --------------------------------------------------------------------
def test_download_release_verified_success(tmp_path, monkeypatch):
    monkeypatch.setattr(ssrf, "_validate_url", lambda url: None)
    # Test multi-chunk stream
    chunk1 = b"PK\x03\x04valid-zip"
    chunk2 = b"-content-part2"
    content = chunk1 + chunk2
    content_hash = hashlib.sha256(content).hexdigest()

    captured_reqs = []
    captured_timeouts = []

    def _fake_urlopen(req, timeout=None):
        captured_reqs.append(req)
        captured_timeouts.append(timeout)
        return _FakeStreamResponse([chunk1, chunk2])

    monkeypatch.setattr(auf.urllib.request, "urlopen", _fake_urlopen)

    res = auf.download_release(
        asset_url="https://github.com/test/valid.zip",
        asset_name="valid.zip",
        expected_sha256=f"sha256: {content_hash.upper()} ",
        dest_dir=tmp_path / "nested_dir" / "deep",
    )

    zip_file = tmp_path / "nested_dir" / "deep" / "valid.zip"
    assert res == {
        "ok": True,
        "path": str(zip_file),
        "sha256": content_hash,
        "verified": True,
        "size_bytes": len(content),
        "staging_dir": str(tmp_path / "nested_dir" / "deep"),
    }
    assert zip_file.read_bytes() == content
    assert captured_timeouts == [60]
    assert captured_reqs[0].get_header("User-agent") == auf._user_agent()


def test_download_release_default_allow_unverified_is_false(tmp_path, monkeypatch):
    monkeypatch.setattr(ssrf, "_validate_url", lambda url: None)
    content = b"PK\x03\x04test"
    content_hash = hashlib.sha256(content).hexdigest()

    monkeypatch.setattr(
        auf.urllib.request, "urlopen", lambda req, timeout=None: _FakeStreamResponse([content])
    )

    # Call without allow_unverified (tests default False)
    res = auf.download_release(
        asset_url="https://github.com/test/valid.zip",
        asset_name="valid.zip",
        dest_dir=tmp_path,
    )

    zip_file = tmp_path / "valid.zip"
    assert res == {
        "ok": False,
        "error": "expected_sha256 is required: refusing to hand back an unverified release archive",
        "got": content_hash,
        "path": str(zip_file),
        "hint": "Pass the digest GitHub publishes for the asset, or pass allow_unverified=True to accept the risk deliberately.",
    }


def test_download_release_unverified_accepted_when_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(ssrf, "_validate_url", lambda url: None)
    content = b"PK\x03\x04test"
    content_hash = hashlib.sha256(content).hexdigest()

    monkeypatch.setattr(
        auf.urllib.request, "urlopen", lambda req, timeout=None: _FakeStreamResponse([content])
    )

    res = auf.download_release(
        asset_url="https://github.com/test/valid.zip",
        asset_name="valid.zip",
        expected_sha256=None,
        allow_unverified=True,
        dest_dir=tmp_path,
    )

    zip_file = tmp_path / "valid.zip"
    assert res == {
        "ok": True,
        "path": str(zip_file),
        "sha256": content_hash,
        "verified": False,
        "size_bytes": len(content),
        "staging_dir": str(tmp_path),
    }


def test_download_release_sha_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(ssrf, "_validate_url", lambda url: None)
    content = b"PK\x03\x04test"
    content_hash = hashlib.sha256(content).hexdigest()
    wrong_hash = "0" * 64

    monkeypatch.setattr(
        auf.urllib.request, "urlopen", lambda req, timeout=None: _FakeStreamResponse([content])
    )

    res = auf.download_release(
        asset_url="https://github.com/test/valid.zip",
        asset_name="valid.zip",
        expected_sha256=wrong_hash,
        dest_dir=tmp_path,
    )

    zip_file = tmp_path / "valid.zip"
    assert res == {
        "ok": False,
        "error": "sha256 mismatch after download",
        "expected": wrong_hash,
        "got": content_hash,
        "path": str(zip_file),
    }


def test_download_release_default_dest_dir_prefix(monkeypatch):
    monkeypatch.setattr(ssrf, "_validate_url", lambda url: None)
    content = b"PK\x03\x04temp"

    monkeypatch.setattr(
        auf.urllib.request, "urlopen", lambda req, timeout=None: _FakeStreamResponse([content])
    )

    res = auf.download_release(
        asset_url="https://github.com/test/temp.zip",
        asset_name="temp.zip",
        allow_unverified=True,
    )
    assert res["ok"] is True
    assert Path(res["staging_dir"]).name.startswith("arena-update-")
    assert Path(res["path"]).exists()
    assert Path(res["path"]).read_bytes() == content

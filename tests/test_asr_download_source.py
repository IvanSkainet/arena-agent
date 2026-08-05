"""ASR bootstrap downloads must be HTTPS, from known hosts, or not happen.

`arena/mcp/tool_asr.py` fetches ffmpeg, whisper.cpp and a model file, then
runs the first two. `asr.bootstrap` takes `model_url` and
`whisper_zip_url` straight from the tool call, and `_download_atomic`
passed them to `urllib.request.urlopen`, which speaks whatever scheme it
is handed.

Bug #55, verified by execution:

    _download_atomic("file:///etc/hostname", dest, force=True)
    -> {"ok": True, "size_bytes": 9}, and dest contained the host name

So a "download" could read local files. `http://` was accepted too --
an unencrypted fetch of a binary that then gets executed.

Pinning the scheme alone would not be enough: arbitrary HTTPS still lets
a caller point the bootstrap at any server and have the result run as
whisper-cli. The allowed hosts are derived from the three default URL
constants rather than typed out again, so a new source cannot be added
to one place and forgotten in the other.

Sabotage record (mandatory per AGENTS.md):
  1. dropping the scheme check
     -> test_non_https_schemes_are_refused fails (file:// reads a file).
  2. dropping the host check
     -> test_unknown_hosts_are_refused fails.
  3. hardcoding the host set instead of deriving it
     -> test_allowed_hosts_are_derived_from_the_default_urls fails.
"""
from __future__ import annotations

import urllib.parse

import pytest

from arena.mcp import tool_asr

# ---------------------------------------------------------------------------
# Scheme.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "file:///etc/hostname",
    "file:///etc/passwd",
    "http://huggingface.co/model.bin",
    "ftp://huggingface.co/model.bin",
    "data:text/plain;base64,aGk=",
    "gopher://huggingface.co/x",
    "//huggingface.co/model.bin",
    "huggingface.co/model.bin",
])
def test_non_https_schemes_are_refused(url):
    with pytest.raises(ValueError, match="scheme"):
        tool_asr._require_https(url)


def test_a_file_url_cannot_be_used_to_read_local_files(tmp_path):
    """The original repro, as an executable check."""
    secret = tmp_path / "secret.txt"
    secret.write_text("sensitive", encoding="utf-8")
    dest = tmp_path / "out.bin"

    with pytest.raises(ValueError):
        tool_asr._download_atomic(f"file://{secret}", dest, force=True)

    assert not dest.exists(), "a local file was copied in as a 'download'"


# ---------------------------------------------------------------------------
# Host.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://evil.example/model.bin",
    "https://127.0.0.1/model.bin",
    "https://localhost:8080/model.bin",
    "https://huggingface.co.evil.example/model.bin",
    "https://169.254.169.254/latest/meta-data/",
])
def test_unknown_hosts_are_refused(url):
    """Including the cloud metadata address and a lookalike domain."""
    with pytest.raises(ValueError, match="refusing to download from"):
        tool_asr._require_https(url)


@pytest.mark.parametrize("url", [
    tool_asr._FFMPEG_ZIP_URL,
    tool_asr._WHISPER_ZIP_URL,
    tool_asr._MODEL_URL_TMPL.format(name="ggml-base.bin"),
])
def test_the_default_urls_pass_their_own_validator(url):
    """A validator that rejects the tool's own defaults is a broken tool."""
    tool_asr._require_https(url)


def test_allowed_hosts_are_derived_from_the_default_urls():
    """Pinning must not be a second list that can drift.

    If someone adds a fourth download source, changing the URL constant
    has to be enough -- a hand-maintained host set would silently reject
    the new source, and the natural fix would be to widen it carelessly.
    """
    expected = {
        urllib.parse.urlparse(u).hostname
        for u in (tool_asr._FFMPEG_ZIP_URL, tool_asr._WHISPER_ZIP_URL,
                  tool_asr._MODEL_URL_TMPL)
    }
    assert set(tool_asr._ALLOWED_DOWNLOAD_HOSTS) == expected


def test_the_host_set_is_not_empty_or_wildcarded():
    hosts = set(tool_asr._ALLOWED_DOWNLOAD_HOSTS)
    assert hosts, "an empty allowlist would refuse everything including defaults"
    assert "" not in hosts
    assert "*" not in hosts


# ---------------------------------------------------------------------------
# The check is actually wired into the download path.
# ---------------------------------------------------------------------------

def test_download_atomic_validates_before_opening_anything(tmp_path, monkeypatch):
    """The guard must run before urlopen, not after."""
    opened = []
    monkeypatch.setattr(tool_asr.urllib.request, "urlopen",
                        lambda *a, **kw: opened.append(a) or (_ for _ in ()).throw(
                            AssertionError("urlopen must not be reached")))

    with pytest.raises(ValueError):
        tool_asr._download_atomic("https://evil.example/x.bin",
                                  tmp_path / "x.bin", force=True)

    assert not opened


def test_an_existing_file_is_still_skipped_without_a_network_call(tmp_path):
    """The fast path must keep working: bootstrap is often a no-op."""
    dest = tmp_path / "model.bin"
    dest.write_bytes(b"already here")

    result = tool_asr._download_atomic(
        tool_asr._MODEL_URL_TMPL.format(name="ggml-base.bin"), dest)

    assert result["ok"] is True
    assert result["skipped"] is True

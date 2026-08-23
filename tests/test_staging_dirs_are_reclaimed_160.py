"""#160 -- every failed download left an empty staging tree in %TEMP% forever.

`download_release()` creates `tempfile.mkdtemp(prefix="arena-update-")` *before*
the SSRF check and before a single byte is fetched. Every early `return _err(...)`
after that point therefore abandoned the directory: a rejected URL, a DNS
failure, an oversized archive, a digest mismatch. Nothing ever reclaimed them.

Measured on the operator's Windows install running 4.169.50:

    191 `arena-update-*` trees in %TEMP%, 185 of them completely empty,
    accumulating at 4-8 per day -- one per update check that did not result
    in an install.

The issue described the leak as retained *release archives* (~4 MB each). That
is the smaller half: only 4 of the 191 trees had finished (`done.txt`), and 2
held a zip. The dominant leak is the empty-on-failure case, which the issue's
proposed "skip trees without done.txt" prune would have kept forever.

The asymmetry this file locks
-----------------------------
Failure must clean up; **success must not**. On Windows the detached mover
copies *from* staging after the bridge process exits, so a successful download's
tree has to outlive the call. Deleting it would break the very update it staged.
A test that only checked "no leaks" could be passed by a fix that breaks
updating, so both directions are asserted here.

The third invariant is ownership: when the caller passes `dest_dir`, the
directory is theirs and may hold unrelated content. Only the `mkdtemp` this
function created is ever removed.
"""

from __future__ import annotations

import hashlib
import http.server
import pathlib
import socketserver
import tempfile
import threading
import urllib.request
from collections.abc import Iterator

import pytest

import arena.admin.auto_update_fetch as fetch
import arena.security_ssrf as ssrf
from arena.admin.auto_update_fetch import download_release

PAYLOAD = b"PK\x03\x04" + b"y" * 8192
GOOD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
BAD_SHA = "sha256:" + "0" * 64


@pytest.fixture
def staging_root(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Point `mkdtemp` at an empty directory so leaks are countable."""
    root = tmp_path / "tmpdir"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def _staging_trees(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(root.glob("arena-update-*"))


@pytest.fixture
def release_server() -> Iterator[str]:
    """Serve PAYLOAD over loopback and allow the client to reach it."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib API
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)

        def log_message(self, *_args: object) -> None:
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/release.zip"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def allow_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the loopback test server through the SSRF and public-URL guards.

    Those guards are correct and tested elsewhere; here they would simply
    prevent the success path from ever executing.
    """
    monkeypatch.setattr(ssrf, "_validate_url", lambda _url: None)
    monkeypatch.setattr(
        fetch,
        "open_public_url",
        lambda req, timeout=60: urllib.request.urlopen(req, timeout=timeout),  # noqa: S310
    )


def test_ssrf_rejection_leaves_no_staging_tree(staging_root: pathlib.Path) -> None:
    result = download_release(
        asset_url="http://127.0.0.1/evil.zip", asset_name="a.zip", expected_sha256=BAD_SHA
    )
    assert result["ok"] is False
    assert "rejected" in result["error"]
    assert _staging_trees(staging_root) == [], (
        "a URL rejected before any download still created and abandoned a "
        "staging directory (#160)"
    )


def test_unreachable_host_leaves_no_staging_tree(staging_root: pathlib.Path) -> None:
    result = download_release(
        asset_url="https://no-such-host.invalid/a.zip",
        asset_name="a.zip",
        expected_sha256=BAD_SHA,
    )
    assert result["ok"] is False
    assert _staging_trees(staging_root) == [], "a failed fetch leaked its staging tree (#160)"


@pytest.mark.usefixtures("allow_loopback")
def test_digest_mismatch_leaves_no_staging_tree(
    staging_root: pathlib.Path, release_server: str
) -> None:
    result = download_release(
        asset_url=release_server, asset_name="a.zip", expected_sha256="sha256:" + "1" * 64
    )
    assert result["ok"] is False
    assert "mismatch" in result["error"]
    assert _staging_trees(staging_root) == [], (
        "a rejected archive left its staging tree -- and the bad zip inside it (#160)"
    )


@pytest.mark.usefixtures("allow_loopback")
def test_missing_digest_leaves_no_staging_tree(
    staging_root: pathlib.Path, release_server: str
) -> None:
    result = download_release(asset_url=release_server, asset_name="a.zip")
    assert result["ok"] is False
    assert "expected_sha256 is required" in result["error"]
    assert _staging_trees(staging_root) == []


@pytest.mark.usefixtures("allow_loopback")
def test_success_keeps_its_staging_tree(
    staging_root: pathlib.Path, release_server: str
) -> None:
    """The other half of the invariant: the mover needs this tree to survive.

    On Windows the mover runs after the bridge exits and copies out of staging.
    A "cleanup" that also removed the successful tree would pass every leak
    assertion above while breaking the update it had just staged.
    """
    result = download_release(
        asset_url=release_server, asset_name="a.zip", expected_sha256=GOOD_SHA
    )
    assert result["ok"] is True, result
    trees = _staging_trees(staging_root)
    assert len(trees) == 1, f"the successful download must keep its tree, got {trees}"
    assert (trees[0] / "a.zip").exists(), (
        "staging tree survived but the archive is gone -- the mover would have "
        "nothing to copy"
    )
    assert result["staging_dir"] == str(trees[0])


def test_caller_supplied_dest_dir_is_never_deleted(tmp_path: pathlib.Path) -> None:
    """Ownership: only the `mkdtemp` we made is ours to remove.

    A caller-provided `dest_dir` may be an install-managed staging root holding
    unrelated content. Cleaning it up on failure would destroy data this
    function was only borrowing.
    """
    caller_dir = tmp_path / "caller-owned"
    caller_dir.mkdir()
    keeper = caller_dir / "precious.txt"
    keeper.write_text("must survive", encoding="utf-8")

    result = download_release(
        asset_url="https://no-such-host.invalid/a.zip",
        asset_name="a.zip",
        expected_sha256=BAD_SHA,
        dest_dir=str(caller_dir),
    )

    assert result["ok"] is False
    assert caller_dir.exists(), "cleanup deleted a directory it did not create"
    assert keeper.read_text(encoding="utf-8") == "must survive", (
        "cleanup destroyed caller-owned content"
    )

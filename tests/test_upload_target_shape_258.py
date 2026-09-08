"""Upload targets that cannot hold bytes answer 400, not 500.

Found by the Schemathesis gate on PR #292: ``POST /v1/upload?path=~``
resolved to the home directory itself, reached ``write_bytes()`` and the
IsADirectoryError came back as an opaque ``500 Internal error``. A caller
mistake must name itself; only a real bug is allowed to be a 500.

Two shapes are refused here:

* the target itself is an existing directory;
* a parent component is an existing file, which makes the
  ``mkdir(parents=True)`` inside the handler raise NotADirectoryError.
"""
from __future__ import annotations

import os

import pytest

from arena.files.sandbox import validate_upload_target


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    root = home / "workspace"
    root.mkdir()
    bridge_py = home / "bridge.py"
    bridge_py.write_text("# bridge\n")
    # "~" must expand to the fake home, not to the machine's real one.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return {"home": home, "root": root, "bridge_py": bridge_py}


def _validate(target: str, sandbox):
    return validate_upload_target(
        target,
        root=sandbox["root"],
        home=sandbox["home"],
        bridge_py=sandbox["bridge_py"],
    )


def test_uploading_onto_the_home_directory_is_a_named_refusal(sandbox):
    path, err, status = _validate("~", sandbox)

    assert path is None
    assert status == 400
    assert err == "upload path is a directory, not a file"


def test_uploading_onto_any_existing_directory_is_refused(sandbox):
    (sandbox["root"] / "notes").mkdir()

    path, err, status = _validate("~/workspace/notes", sandbox)

    assert path is None
    assert status == 400
    assert "directory" in (err or "")


def test_a_parent_that_is_a_file_is_refused_before_mkdir(sandbox):
    (sandbox["root"] / "notes.txt").write_text("hi\n")

    path, err, status = _validate("~/workspace/notes.txt/inner.bin", sandbox)

    assert path is None
    assert status == 400
    assert "notes.txt" in (err or "")


def test_a_deep_parent_that_is_a_file_is_refused_too(sandbox):
    (sandbox["root"] / "notes.txt").write_text("hi\n")

    path, err, status = _validate(
        "~/workspace/notes.txt/a/b/inner.bin", sandbox,
    )

    assert path is None
    assert status == 400
    assert "notes.txt" in (err or "")


def test_an_ordinary_new_file_still_passes(sandbox):
    path, err, status = _validate("~/workspace/new/file.bin", sandbox)

    assert err is None
    assert status == 200
    assert path is not None
    assert path.name == "file.bin"


def test_overwriting_an_existing_file_still_passes(sandbox):
    (sandbox["root"] / "old.bin").write_bytes(b"old")

    path, err, status = _validate("~/workspace/old.bin", sandbox)

    assert err is None
    assert status == 200
    assert path is not None


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFOs only")
def test_a_fifo_target_is_refused_before_it_can_park_the_loop(sandbox):
    """A FIFO is not a directory and not a missing file, so every earlier
    check waves it through -- and then `write_bytes()` blocks until a
    reader shows up, with the event loop inside it (cubic)."""
    fifo = sandbox["root"] / "pipe"
    os.mkfifo(fifo)

    path, err, status = _validate("~/workspace/pipe", sandbox)

    assert path is None
    assert status == 400
    assert err == "upload path is not a regular file"


def _symlink_or_skip(link, target, *, directory: bool = False) -> None:
    """Make a symlink, or skip: unprivileged Windows cannot make them."""
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this account cannot create symlinks: {exc}")


def test_a_dangling_symlink_parent_is_refused(sandbox):
    """`exists()` follows symlinks, so a broken one answered False to both
    shape checks and the refusal arrived as a 500 out of mkdir (cubic)."""
    _symlink_or_skip(sandbox["root"] / "gone", sandbox["root"] / "nothing-here")

    path, err, status = _validate("~/workspace/gone/file.bin", sandbox)

    assert path is None
    assert status == 400
    assert "gone" in (err or "")


def test_a_symlink_to_a_real_directory_still_passes(sandbox):
    """The refusal is about broken links, not about links."""
    real = sandbox["root"] / "real"
    real.mkdir()
    _symlink_or_skip(sandbox["root"] / "link", real, directory=True)

    path, err, status = _validate("~/workspace/link/file.bin", sandbox)

    assert err is None
    assert status == 200
    assert path is not None

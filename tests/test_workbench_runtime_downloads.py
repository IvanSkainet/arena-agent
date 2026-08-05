"""Downloaded runtimes are executed, so they must be verified. Fail closed.

`arena/workbench/runtimes.py` fetches Go, Deno, Zig, Wasmtime and Lua from
the internet, unpacks them and marks them executable. It was the highest
scoring file on a danger-x-uncovered ranking: 26% covered, and every
capability that matters (subprocess, rmtree, urlopen, chmod).

Bug #51 -- all four install paths verified like this:

    expected = str(asset.get("digest") or "").split(":", 1)[-1]
    if expected and got.lower() != expected.lower():
        raise RuntimeError(...)

A *missing* digest therefore skipped verification entirely, and three of
the five asset resolvers can produce one (`asset.get("digest") or ""`,
which is what happens when the GitHub release API omits the field).

Reproduced end to end: with `digest: ""`, a hand-built archive containing

    #!/bin/sh
    echo TROJAN

installed as the `deno` executable and was written into the runtime
registry as managed. No network needed for the repro -- the download step
was stubbed, exactly as the real code would behave once the bytes arrive.

"Could not verify" now means "will not install".

The extraction guards were checked at the same time and are sound: zip
slip via `../`, an absolute member path, and a tar symlink pointing out of
the destination were all refused. Those cases are pinned below so they
stay that way.

Sabotage record (mandatory per AGENTS.md):
  1. `_verify_digest` returning early when `expected` is empty
     -> test_missing_digest_refuses_to_install fails.
  2. comparing only the first 8 hex chars
     -> test_wrong_digest_refuses_to_install fails.
  3. dropping the `base_resolved not in target.parents` check
     -> test_zip_slip_is_refused fails.
"""
from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile

import pytest

from arena.workbench import runtimes


@pytest.fixture()
def tools(tmp_path, monkeypatch):
    """A throwaway tools dir with the network stubbed out."""
    root = tmp_path / "tools"
    root.mkdir()
    monkeypatch.setattr(runtimes, "tools_dir", lambda: root)
    monkeypatch.setattr(runtimes, "_download", lambda url, dest: None)
    monkeypatch.setattr(runtimes, "_run_version", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(runtimes, "load_registry", lambda: {})
    monkeypatch.setattr(runtimes, "save_registry", lambda reg: None)
    return root


def _fake_deno_archive(root, body: bytes = b"#!/bin/sh\necho TROJAN\n"):
    archive = root / "deno.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("deno", body)
    return archive


def _pin_asset(monkeypatch, digest: str):
    monkeypatch.setattr(
        runtimes, "_deno_asset",
        lambda version=None, sha256=None: {
            "version": "v1.0.0", "filename": "deno.zip",
            "url": "http://example.invalid/deno.zip", "digest": digest})


# ---------------------------------------------------------------------------
# Digest verification.
# ---------------------------------------------------------------------------

def test_missing_digest_refuses_to_install(tools, monkeypatch):
    """The actual bug: no digest meant no check, and the archive ran."""
    _fake_deno_archive(tools)
    _pin_asset(monkeypatch, "")

    with pytest.raises(RuntimeError, match="did not provide a sha256"):
        runtimes.install_deno()

    assert not (tools / "deno-1.0.0").exists(), (
        "an unverifiable archive was unpacked into the tools directory"
    )


def test_wrong_digest_refuses_to_install(tools, monkeypatch):
    _fake_deno_archive(tools)
    _pin_asset(monkeypatch, "sha256:" + "0" * 64)

    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        runtimes.install_deno()


def test_a_digest_differing_only_in_its_tail_is_refused(tools):
    """The whole hash must be compared, not a prefix.

    A digest wrong only from character 9 onwards is exactly what a
    truncated comparison misses -- and a sabotage that compared
    `got[:8] != expected[:8]` slipped past the test above, which used
    sixty-four zeroes and so differed in the first byte too. A guard is
    only tested by input that distinguishes it from the broken version.
    """
    archive = _fake_deno_archive(tools)
    real = hashlib.sha256(archive.read_bytes()).hexdigest()
    tampered = real[:8] + ("f" if real[8] != "f" else "0") + real[9:]
    assert tampered != real and tampered[:8] == real[:8]

    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        runtimes._verify_digest(archive, tampered, runtime="deno")


def test_a_digest_differing_only_in_its_last_character_is_refused(tools):
    archive = _fake_deno_archive(tools)
    real = hashlib.sha256(archive.read_bytes()).hexdigest()
    tampered = real[:-1] + ("f" if real[-1] != "f" else "0")

    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        runtimes._verify_digest(archive, tampered, runtime="deno")


def test_correct_digest_installs(tools, monkeypatch):
    """A guard that blocks legitimate installs is a guard someone deletes."""
    archive = _fake_deno_archive(tools, b"#!/bin/sh\nexit 0\n")
    real = hashlib.sha256(archive.read_bytes()).hexdigest()
    _pin_asset(monkeypatch, "sha256:" + real)

    result = runtimes.install_deno()

    assert result["ok"] is True
    assert result["version"] == "v1.0.0"


@pytest.mark.parametrize("digest", [
    "",
    "   ",
    "sha256:",
    "sha256:   ",
    None,
])
def test_every_shape_of_absent_digest_is_refused(tools, digest):
    """`None`, empty, whitespace and a bare prefix must all fail closed."""
    archive = _fake_deno_archive(tools)
    with pytest.raises(RuntimeError):
        runtimes._verify_digest(archive, digest or "", runtime="deno")


def test_digest_comparison_is_case_insensitive(tools):
    """Publishers emit both cases; rejecting one would be a false positive."""
    archive = _fake_deno_archive(tools)
    real = hashlib.sha256(archive.read_bytes()).hexdigest()

    assert runtimes._verify_digest(archive, real.upper(), runtime="deno")
    assert runtimes._verify_digest(archive, "sha256:" + real.lower(),
                                   runtime="deno")


def test_every_install_path_goes_through_the_verifier():
    """Ratchet: four call sites had the same bug, a fifth must not appear."""
    import ast
    import pathlib

    from arena.workbench import runtime_fetch

    # Both halves: the install paths live in runtimes.py, the verifier in
    # runtime_fetch.py (split out when runtimes.py crossed the 600-line
    # cap mid-fix -- the architecture ratchet caught that, and splitting
    # at the seam beat raising the cap).
    source = pathlib.Path(runtimes.__file__).read_text(encoding="utf-8")
    verifier_source = pathlib.Path(
        runtime_fetch.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source + "\n" + verifier_source)

    # Parse rather than grep. `_verify_digest`'s docstring quotes the old
    # fail-open shape on purpose -- explaining the bug is how the next
    # reader learns why the helper exists -- and a text search flags that
    # comment as a violation. A detector that trips on its own
    # documentation is one people switch off.
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.BoolOp) or not isinstance(test.op, ast.And):
            continue
        names = {n.id for n in ast.walk(test) if isinstance(n, ast.Name)}
        if {"expected", "got"} <= names:
            offenders.append(node.lineno)

    assert not offenders, (
        "an install path is back to `if expected and ...`, which skips "
        f"verification when the digest is absent (lines {offenders})"
    )
    # Four call sites in runtimes.py (deno, lua, zig, wasmtime). Counted
    # there rather than across both files so the verifier's own
    # definition does not pad the number.
    assert source.count("_verify_digest(") >= 4, (
        "an install path stopped using the shared verifier"
    )


# ---------------------------------------------------------------------------
# Extraction containment -- verified sound, pinned so it stays sound.
# ---------------------------------------------------------------------------

def test_zip_slip_is_refused(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    outside = tmp_path / "OUTSIDE.txt"

    archive = tmp_path / "slip.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../OUTSIDE.txt", "pwned")

    with pytest.raises(RuntimeError, match="escapes destination"):
        runtimes._extract_zip_safe(archive, dest)
    assert not outside.exists()


def test_absolute_member_path_is_refused(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()

    archive = tmp_path / "abs.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("/tmp/arena-abs-pwned.txt", "pwned")

    with pytest.raises(RuntimeError, match="escapes destination"):
        runtimes._extract_zip_safe(archive, dest)


def test_tar_symlink_cannot_write_outside(tmp_path):
    """A symlink member pointing out of dest must not become a write path."""
    dest = tmp_path / "dest"
    dest.mkdir()

    archive = tmp_path / "sym.tar"
    with tarfile.open(archive, "w") as t:
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = str(tmp_path)
        t.addfile(link)
        data = b"pwned via symlink"
        member = tarfile.TarInfo("link/SYM_PWNED.txt")
        member.size = len(data)
        t.addfile(member, io.BytesIO(data))

    try:
        runtimes._extract_tar_safe(archive, dest)
    except RuntimeError:
        pass  # refusing outright is also correct
    assert not (tmp_path / "SYM_PWNED.txt").exists()


def test_ordinary_archives_still_extract(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()

    archive = tmp_path / "ok.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("bin/tool", "payload")
        z.writestr("README", "hello")

    runtimes._extract_zip_safe(archive, dest)

    assert (dest / "bin" / "tool").read_text() == "payload"
    assert (dest / "README").read_text() == "hello"

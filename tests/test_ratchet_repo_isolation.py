"""T74: scanner sabotage inputs must not alias the real working tree."""
from pathlib import Path

import pytest


@pytest.mark.parametrize("relative", [
    "scripts/global_patch_baseline.json",
    "scripts/posix_shell_test_ratchet.py",
    ".github/workflows/ci.yml",
    "arena/constants.py",
])
def test_private_scanner_inputs_do_not_alias_source(isolated_ratchet_repo, relative):
    source = Path(__file__).resolve().parents[1] / relative
    private = isolated_ratchet_repo / relative
    original = source.read_bytes()
    assert private.read_bytes() == original
    assert not private.is_symlink()
    private.write_bytes(b"T74 private sabotage\n")
    assert source.read_bytes() == original


def test_private_scan_keeps_complete_input_inventory(isolated_ratchet_repo):
    source = Path(__file__).resolve().parents[1]
    for directory in ("arena", "scripts", "tests", ".github"):
        expected = {
            p.relative_to(source / directory)
            for p in (source / directory).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        }
        actual = {
            p.relative_to(isolated_ratchet_repo / directory)
            for p in (isolated_ratchet_repo / directory).rglob("*")
            if p.is_file()
        }
        assert actual == expected

"""Configured Graph must be able to stage every referenced constraint.

Dependabot's SharedFileFetcher follows `.in` constraints, but returns only
child_requirement_txt_files / child_requirement_in_files; constraints_files
excludes already-fetched children. A `.lock` child is therefore fetched and
then discarded. This is the missing requirements-ci.lock in run44386362882,
not an absent repository file or a pip resolver conflict.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest import TestCase

import pytest
from pip._internal.exceptions import InstallationError
from pip._internal.network.session import PipSession
from pip._internal.req.req_file import parse_requirements

CHECK = TestCase()
ROOT = Path(__file__).resolve().parents[1]


def _parse(path: Path) -> list:
    with PipSession() as session:
        return list(parse_requirements(str(path), session=session))


def test_text_projection_contains_every_constraint_needed_by_root_inputs(tmp_path):
    # Model the relevant returned extension projection, not the host checkout:
    # pip must not accidentally find an unstaged .lock next to the .in files.
    for source in [*ROOT.glob("requirements-*.in"), *ROOT.glob("requirements-*.txt")]:
        shutil.copy2(source, tmp_path / source.name)
    for name in ("requirements-bench.in", "requirements-fuzz.in"):
        requirements = _parse(tmp_path / name)
        CHECK.assertTrue(requirements)
        CHECK.assertTrue(any(item.constraint for item in requirements))
    CHECK.assertFalse((tmp_path / "requirements-ci.lock").exists())


def test_old_nontext_constraint_reproduces_the_graph_failure(tmp_path):
    (tmp_path / "requirements-fuzz.in").write_text("-c requirements-ci.lock\npytest==9.1.1\n")
    with pytest.raises(InstallationError, match="requirements-ci.lock"):
        _parse(tmp_path / "requirements-fuzz.in")


def test_ci_text_lock_keeps_its_compile_pair_and_hashes():
    from scripts.check_lock_freshness import check_pair

    CHECK.assertEqual(check_pair("requirements-ci"), [])
    CHECK.assertIn("--output-file=requirements-ci.txt", (ROOT / "requirements-ci.txt").read_text())
    CHECK.assertFalse((ROOT / "requirements-ci.lock").exists())


def test_relock_selects_and_stages_the_text_output():
    workflow = (ROOT / ".github/workflows/relock-dependabot.yml").read_text()
    CHECK.assertIn('if [ "$in_file" = "requirements-ci.in" ]; then\n              lock_file="requirements-ci.txt"', workflow)
    CHECK.assertIn("git add requirements-*.lock requirements-ci.txt", workflow)
    CHECK.assertIn("git diff --quiet -- 'requirements-*.lock' requirements-ci.txt", workflow)

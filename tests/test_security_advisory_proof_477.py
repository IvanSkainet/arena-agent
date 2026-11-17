"""A fix in an older branch does not prove safety in a newer release line."""
from __future__ import annotations

from unittest import TestCase

import pytest

from arena.security_advisory_proof import advisory_floor
from arena.security_alerts import _dependabot_row
from arena.security_manifest_proof import manifest_fixes

CHECK = TestCase()


def _branch(affected: str, patched: str | None) -> dict:
    return {"package": {"name": "demo", "ecosystem": "pip"},
            "vulnerable_version_range": affected,
            "first_patched_version": {"identifier": patched} if patched else None}


def test_all_advisory_release_lines_control_the_proof_floor() -> None:
    advisory = {"vulnerabilities": [_branch("< 2.8.19", "2.8.19"),
                                    _branch(">= 2.9.0, < 2.9.18", "2.9.18")]}
    floor = advisory_floor(advisory, "demo", "pip")
    CHECK.assertEqual(floor, "2.9.18")
    CHECK.assertFalse(manifest_fixes("requirements.txt", "demo==2.9.0", "demo", floor))
    CHECK.assertFalse(manifest_fixes("requirements.txt", "demo>=2.8.19", "demo", floor))
    CHECK.assertTrue(manifest_fixes("requirements.txt", "demo>=2.9.18", "demo", floor))
    row = _dependabot_row({"security_advisory": advisory,
                          "security_vulnerability": advisory["vulnerabilities"][0],
                          "dependency": {"package": {"name": "demo", "ecosystem": "pip"}}})
    CHECK.assertEqual(row["proof_floor"], "2.9.18")


@pytest.mark.parametrize(("affected", "patched"), [
    (">= 2.9.0", "2.9.18"), ("< 2.8.19 || >=2.9,<2.9.18", "2.8.19"),
    ("<= 2.9.18", "2.9.18"), ("< 3.0", None), ("< 3.0", "3.0rc1"),
    ("< 3.0rc1", "3.0"),
])
def test_unknown_unbounded_or_inconsistent_branch_keeps_alert(affected, patched) -> None:
    advisory = {"vulnerabilities": [_branch("< 2.8.19", "2.8.19"), _branch(affected, patched)]}
    CHECK.assertIsNone(advisory_floor(advisory, "demo", "pip"))


def test_unrelated_package_cannot_raise_or_supply_missing_proof() -> None:
    advisory = {"vulnerabilities": [_branch("< 2.8.19", "2.8.19")]}
    CHECK.assertIsNone(advisory_floor(advisory, "other", "pip"))
    CHECK.assertIsNone(advisory_floor({}, "demo", "pip"))
    CHECK.assertIsNone(advisory_floor(advisory, "demo", "npm"))


@pytest.mark.parametrize("target", [{}, {"name": "demo"}, {"ecosystem": "pip"},
                                    {"name": 7, "ecosystem": "pip"}, None])
def test_malformed_identity_never_silently_removes_a_branch(target) -> None:
    invalid = _branch("< 3.0", "3.0")
    invalid["package"] = target
    advisory = {"vulnerabilities": [_branch("< 2.8.19", "2.8.19"), invalid]}
    CHECK.assertIsNone(advisory_floor(advisory, "demo", "pip"))


def test_inverted_range_is_unknown_not_exempt() -> None:
    CHECK.assertIsNone(advisory_floor({"vulnerabilities": [_branch(">= 4.0, < 3.0", "3.0")]},
                                    "demo", "pip"))

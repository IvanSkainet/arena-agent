"""The release-published gate must not block the release it is guarding.

`scripts/release_published_check.py` exists for a real incident:
v4.169.5 through v4.169.9 were tagged, green on 35/35 CI jobs, and
invisible to every install, because `auto_update.py` reads
`releases/latest` and GitHub answers with published releases, not tags.

But the gap arithmetic scored ANY minor bump as 99, and 99 exceeds the
one-release lead the non-strict path allows. RELEASE.md commits the
version bump to master *before* the release is cut, and `Version sync`
is a required status check -- so a minor release could not be merged
without bypassing the master ruleset. A patch release never tripped it,
which is how it survived to v4.170.0.

The message was misleading too: "99 unpublished releases have piled up"
is not a count of anything. It sent me looking for 99 drafts; there
were two.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "release_published_check.py"


def _load():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("release_published_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def gate():
    return _load()


def test_script_exists():
    assert SCRIPT.is_file(), f"{SCRIPT} is missing; CI and preflight both run it"


def test_a_minor_bump_is_one_step_not_a_pile_up(gate):
    """4.169.50 -> 4.170.0 is the ordinary release flow, not an emergency."""
    assert gate._gap((4, 170, 0), (4, 169, 50)) == 1


def test_a_major_bump_is_also_one_step(gate):
    assert gate._gap((5, 0, 0), (4, 170, 0)) == 1


def test_a_patch_lead_of_one_is_still_one(gate):
    """The pre-existing behaviour that already worked must not change."""
    assert gate._gap((4, 169, 51), (4, 169, 50)) == 1


def test_a_real_pile_up_is_still_counted(gate):
    """The incident this gate was written for: five releases deep."""
    assert gate._gap((4, 169, 9), (4, 169, 4)) == 5


def test_no_lead_is_zero(gate):
    assert gate._gap((4, 170, 0), (4, 170, 0)) == 0


def test_the_release_pr_is_not_blocked_by_its_own_bump(gate, monkeypatch, capsys):
    """End to end: the non-strict path must pass during a minor release.

    This is the case that deadlocked #250 -- `Version sync` is required,
    and it could not go green until the release existed, which required
    the merge that the check was blocking.
    """
    monkeypatch.setattr(gate, "current_version", lambda: "4.170.0")
    monkeypatch.setattr(gate, "_api", lambda path: {
        "tag_name": "v4.169.50",
        "assets": [{"name": "arena-agent.zip"}],
    })
    assert gate.main([]) == 0
    assert "OK" in capsys.readouterr().out


def test_strict_still_demands_the_release_exists(gate, monkeypatch, capsys):
    """The guarantee must survive the fix.

    On a tag, `--strict` sets the allowed lead to zero, so a version that
    was tagged but never published is still caught.
    """
    monkeypatch.setattr(gate, "current_version", lambda: "4.170.0")
    monkeypatch.setattr(gate, "_api", lambda path: {
        "tag_name": "v4.169.50",
        "assets": [{"name": "arena-agent.zip"}],
    })
    assert gate.main(["--strict"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_a_published_release_ahead_of_the_tree_is_refused(gate, monkeypatch, capsys):
    """Published metadata must not advertise code master does not have."""
    monkeypatch.setattr(gate, "current_version", lambda: "4.169.50")
    monkeypatch.setattr(gate, "_api", lambda path: {
        "tag_name": "v4.170.0",
        "assets": [{"name": "arena-agent.zip"}],
    })
    assert gate.main([]) == 1
    assert "ahead of the source tree" in capsys.readouterr().out


def test_the_readme_alias_asset_is_still_required(gate, monkeypatch, capsys):
    """`releases/latest/download/arena-agent.zip` 404s without the alias."""
    monkeypatch.setattr(gate, "current_version", lambda: "4.170.0")
    monkeypatch.setattr(gate, "_api", lambda path: {
        "tag_name": "v4.170.0",
        "assets": [{"name": "arena-agent-v4.170.0.zip"}],
    })
    assert gate.main([]) == 1
    assert "arena-agent.zip" in capsys.readouterr().out

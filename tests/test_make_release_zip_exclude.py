"""v4.83.0 — release-zip exclusion of rotated runtime logs.

While cutting v4.83.0 a tracked ``requests.jsonl.2`` (a logrotate-style
rotated request log) leaked into the release zip: ``should_exclude``
matched the exact base name ``requests.jsonl`` but not the rotated
``requests.jsonl.2``. The fix matches runtime logs on a prefix so any
rotation suffix is excluded. These tests pin that behaviour.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _load():
    spec = importlib.util.spec_from_file_location(
        "make_release_zip", REPO / "scripts" / "make_release_zip.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load()


def test_exact_runtime_logs_excluded():
    for name in ("requests.jsonl", "audit.jsonl", "bridge.log",
                 "token.txt", "facts.jsonl", "history.jsonl"):
        assert _mod.should_exclude(name) is True, name


def test_rotated_runtime_logs_excluded():
    # The actual v4.83.0 regression: rotated logs must not ship.
    for name in ("requests.jsonl.1", "requests.jsonl.2", "audit.jsonl.3",
                 "bridge.log.1", "bridge.log.12"):
        assert _mod.should_exclude(name) is True, name


def test_rotated_logs_excluded_even_under_arena_bridge_prefix():
    assert _mod.should_exclude("arena-bridge/requests.jsonl.2") is True


def test_normal_files_are_kept():
    for name in ("arena/mobile/recording.py", "unified_bridge.py",
                 "arena/constants.py", "install.sh", "README.md"):
        assert _mod.should_exclude(name) is False, name


def test_tests_and_vcs_dirs_still_excluded():
    assert _mod.should_exclude("tests/test_foo.py") is True
    assert _mod.should_exclude(".git/config") is True
    assert _mod.should_exclude("arena/__pycache__/x.pyc") is True

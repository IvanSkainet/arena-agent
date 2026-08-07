"""The claim-order ratchet must fail on the bug and stay quiet otherwise.

A detector that cries wolf gets switched off, and a detector nobody
trusts is worse than none. These tests pin both halves: the shapes it
must catch, and -- at greater length -- the legitimate shapes it must
never touch.

The scanned corpus itself is asserted clean, so a future commit that
reintroduces the #73 shape anywhere under `arena/` or `bin/` fails here
as well as in preflight.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "claim_order_ratchet.py"


def _load():
    spec = importlib.util.spec_from_file_location("claim_order_ratchet", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RATCHET = _load()


def _offenders(source: str, tmp_path: pathlib.Path) -> list[tuple[str, int]]:
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    # Parse-check first: a test fixture with a syntax error would be
    # silently skipped by the scanner and pass for the wrong reason.
    ast.parse(source)
    return RATCHET.scan_file(path)


# --------------------------------------------------------------------
# Shapes that must be caught.
# --------------------------------------------------------------------

BUG_73 = '''
def read_replies(root, consume=True):
    found = []
    for path in sorted(root.glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        found.append(raw)
        if consume:
            path.unlink(missing_ok=True)
    return found
'''

RENAME_AFTER_YIELD = '''
def take(inbox, running):
    for path in inbox.iterdir():
        yield path.read_text()
        path.rename(running / path.name)
'''

RETURN_BEFORE_CLAIM = '''
def first(inbox):
    for path in sorted(inbox.glob("*.json")):
        body = path.read_text()
        if body:
            return body
        path.unlink()
    return None
'''


@pytest.mark.parametrize("source,label", [
    (BUG_73, "bug #73: append before unlink"),
    (RENAME_AFTER_YIELD, "yield before rename"),
    (RETURN_BEFORE_CLAIM, "return before unlink"),
])
def test_offending_shapes_are_caught(source, label, tmp_path):
    assert _offenders(source, tmp_path), f"missed: {label}"


# --------------------------------------------------------------------
# Shapes that must NOT be caught. The longer list on purpose: false
# positives are the failure mode that kills a gate.
# --------------------------------------------------------------------

CLAIM_FIRST = '''
def read_replies(root, consume=True):
    found = []
    for path in sorted(root.glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        if consume:
            try:
                path.unlink()
            except OSError:
                continue
        found.append(raw)
    return found
'''

READ_ONLY_SCAN = '''
def survey(root):
    out = []
    for path in root.glob("*.json"):
        out.append(path.read_text())
    return out
'''

HOUSEKEEPING_ONLY = '''
def sweep(root):
    removed = 0
    for path in root.glob("*.json"):
        path.unlink()
        removed += 1
    return removed
'''

EXCL_GUARDED = '''
import os

def claim_next(inbox, claimed):
    for path in sorted(inbox.glob("*.json")):
        lock = claimed / (path.name + ".lock")
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        os.close(fd)
        raw = path.read_text()
        return raw
    return None
'''

COUNT_WITHOUT_CONSUMING = '''
def depth(root):
    return len(list(root.glob("*.json")))
'''

NO_LISTING_AT_ALL = '''
def process(items):
    out = []
    for item in items:
        out.append(item)
        item.unlink()
    return out
'''


@pytest.mark.parametrize("source,label", [
    (CLAIM_FIRST, "the actual v4.166.2 fix"),
    (READ_ONLY_SCAN, "read-only scan, no claim"),
    (HOUSEKEEPING_ONLY, "prune-style delete, nothing delivered"),
    (EXCL_GUARDED, "O_EXCL lock makes ordering irrelevant"),
    (COUNT_WITHOUT_CONSUMING, "counting a directory"),
    (NO_LISTING_AT_ALL, "not a directory listing"),
])
def test_legitimate_shapes_are_not_flagged(source, label, tmp_path):
    assert not _offenders(source, tmp_path), f"false positive on: {label}"


def test_the_repository_itself_is_clean():
    """The corpus the gate guards must pass it today.

    If this fails, someone reintroduced the shape that produced
    542 deliveries for 300 replies.
    """
    offenders = []
    for path in RATCHET.iter_sources():
        for func_name, lineno in RATCHET.scan_file(path):
            offenders.append(f"{path.relative_to(ROOT)}:{lineno} {func_name}()")
    assert not offenders, "claim-order violations: " + ", ".join(offenders)


def test_preflight_actually_runs_this_gate():
    """A gate wired nowhere is a gate that never fires."""
    source = (ROOT / "scripts" / "preflight.py").read_text(encoding="utf-8")
    assert "claim_order_ratchet.py" in source, "preflight never runs the ratchet"

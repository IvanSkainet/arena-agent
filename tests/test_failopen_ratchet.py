"""The fail-open ratchet must catch the three bugs that motivated it.

Three fixes in two releases had one shape, and each was found separately
because nobody had named the pattern:

    #51  if expected and got.lower() != expected.lower():   runtimes.py
    #54  if not _TOKEN: return True                         helper_server.py
    #61  if expected_sha256:                                auto_update.py

Every one reads as "verify this" and means "verify this, if somebody
supplied the thing to verify against". `scripts/failopen_ratchet.py`
looks for that shape across `arena/`.

A detector like this earns its keep only if two things hold, so both are
tested here against the **actual pre-fix source**, pulled out of git
rather than paraphrased:

  * it catches all three (a detector that misses the cases it was built
    from is decoration);
  * it stays quiet on the tree as it is now, where every remaining
    candidate was read by hand and allow-listed with a reason.

The false-positive half is not hypothetical. The first version flagged
`_apply_authtoken`'s bare `return` as "access granted" and the browser
diagnostics' `expected_output_substr` as a digest. Both were wrong, both
are now regression cases below.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import failopen_ratchet as ratchet  # noqa: E402


def _historic(commit: str, path: str, tmp_path: pathlib.Path) -> pathlib.Path:
    """The file as it was one commit BEFORE the fix landed."""
    result = subprocess.run(
        ["git", "show", f"{commit}~1:{path}"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        pytest.skip(f"history for {commit} unavailable in this checkout")
    target = tmp_path / pathlib.Path(path).name
    target.write_text(result.stdout, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# It catches the bugs it was built from.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("commit,path,expect_shape", [
    ("abc4ac41", "arena/workbench/runtimes.py", "gated-refusal"),
    ("0212b735", "arena/input_helper/helper_server.py", "absent-means-allowed"),
    ("08d8bbd5", "arena/admin/auto_update.py", "gated-refusal"),
])
def test_it_catches_the_original_bugs(tmp_path, commit, path, expect_shape):
    source = _historic(commit, path, tmp_path)

    hits = ratchet.scan_file(source)

    assert hits, f"{path} before {commit} was fail-open and was not flagged"
    assert any(shape == expect_shape for _ln, shape, _src in hits), (
        f"expected a {expect_shape} finding, got {[h[1] for h in hits]}"
    )


def test_the_fixed_versions_are_clean():
    """The same three files, as they stand now, must not be flagged."""
    for path in ("arena/workbench/runtime_fetch.py",
                 "arena/input_helper/helper_server.py",
                 "arena/admin/auto_update_fetch.py"):
        hits = ratchet.scan_file(ROOT / path)
        assert not hits, f"{path} still looks fail-open: {hits}"


# ---------------------------------------------------------------------------
# It stays quiet on legitimate code.
# ---------------------------------------------------------------------------

def test_the_tree_is_clean_or_allow_listed():
    """The whole point: green today, red the moment a fourth one lands."""
    found = ratchet.collect()
    unknown = [f"{rel}:{ln}:{shape}" for rel, ln, shape, _src in found
               if f"{rel}:{ln}:{shape}" not in ratchet.ALLOWLIST]

    assert not unknown, (
        "new fail-open candidates:\n  " + "\n  ".join(unknown)
        + "\n\nFix them, or allow-list with a reason why an empty value is "
          "safe there."
    )


def test_a_bare_return_is_not_read_as_permission(tmp_path):
    """Regression: `_apply_authtoken` ends with a bare `return`.

    "Nothing to configure" is not "access granted", and a detector that
    conflates them gets switched off.
    """
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import os\n"
        "def apply() -> None:\n"
        "    token = os.environ.get('X', '')\n"
        "    if not token:\n"
        "        return\n"
        "    print(token)\n", encoding="utf-8")

    assert ratchet.scan_file(sample) == []


def test_an_optional_heuristic_is_not_read_as_a_digest(tmp_path):
    """Regression: browser diagnostics gate on `expected_output_substr`.

    Nothing in that branch names a secret, so the word "expected" alone
    must not be enough.
    """
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def check(stdout, expected_output_substr=''):\n"
        "    if expected_output_substr and expected_output_substr not in stdout:\n"
        "        return {'isError': True}\n"
        "    return None\n", encoding="utf-8")

    assert ratchet.scan_file(sample) == []


def test_an_optional_header_is_not_read_as_a_check(tmp_path):
    """`if token: headers[...] = ...` skips a header, not a verification."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def call(token, headers):\n"
        "    if token:\n"
        "        headers['Authorization'] = f'Bearer {token}'\n"
        "    return headers\n", encoding="utf-8")

    assert ratchet.scan_file(sample) == []


# ---------------------------------------------------------------------------
# Synthetic examples of each shape, so the detector's contract is explicit.
# ---------------------------------------------------------------------------

def test_shape_a_gated_refusal_is_flagged(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def install(archive, expected_digest=None):\n"
        "    got = sha256(archive)\n"
        "    if expected_digest and got != expected_digest:\n"
        "        raise RuntimeError('sha256 mismatch')\n"
        "    return got\n", encoding="utf-8")

    hits = ratchet.scan_file(sample)

    assert [shape for _ln, shape, _src in hits] == ["gated-refusal"]


def test_shape_b_absent_means_allowed_is_flagged(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "TOKEN = ''\n"
        "def check_auth(header):\n"
        "    if not TOKEN:\n"
        "        return True\n"
        "    return header == TOKEN\n", encoding="utf-8")

    hits = ratchet.scan_file(sample)

    assert [shape for _ln, shape, _src in hits] == ["absent-means-allowed"]


def test_an_unconditional_check_is_not_flagged(tmp_path):
    """What the fixed code looks like -- required, or an explicit opt-out."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def install(archive, expected_digest=None, allow_unverified=False):\n"
        "    got = sha256(archive)\n"
        "    if not expected_digest:\n"
        "        if not allow_unverified:\n"
        "            raise RuntimeError('digest required')\n"
        "    elif got != expected_digest:\n"
        "        raise RuntimeError('sha256 mismatch')\n"
        "    return got\n", encoding="utf-8")

    assert ratchet.scan_file(sample) == []


# ---------------------------------------------------------------------------
# The allowlist has to stay a review record, not a dumping ground.
# ---------------------------------------------------------------------------

def test_every_allowlist_entry_explains_itself():
    for key, reason in ratchet.ALLOWLIST.items():
        assert len(reason) > 60, (
            f"{key} is allow-listed with a reason too short to be one: "
            f"{reason!r}"
        )
        assert key.count(":") == 2, f"{key} is not path:line:shape"


def test_allowlist_entries_point_at_real_lines():
    """A stale entry silently un-guards whatever moved into its place."""
    stale = []
    for key in ratchet.ALLOWLIST:
        rel, lineno, _shape = key.rsplit(":", 2)
        path = ROOT / rel
        if not path.exists():
            stale.append(f"{key} (file gone)")
            continue
        if int(lineno) > len(path.read_text(encoding="utf-8").splitlines()):
            stale.append(f"{key} (past end of file)")

    assert not stale, "stale allowlist entries:\n  " + "\n  ".join(stale)

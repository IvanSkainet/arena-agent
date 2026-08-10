"""v4.169.31 -- the badge bot committed to master whether or not anything changed.

263 of the last 483 commits on master are `chore(badge): refresh
version.json`. Twenty-five of them say `to v4.164.0`; twenty-five more say
`to v4.153.3`. Each one is a single-line diff, and the line is always the
same one:

    -  "updated_at": "2026-08-10T08:30:57Z"
    +  "updated_at": "2026-08-10T09:28:15Z"

The workflow wrote `updated_at` unconditionally, so the file differed on
every run. The "commit if changed" guard right below it was working
perfectly and had something to commit every single time. Real history is
buried better than five to one, and every push needs `git pull --rebase`
first because the bot got there in between.

The timestamp only carries information when the version moves, so it is
now preserved while `tag_name` and `semver` are unchanged. The file comes
out byte-identical, the existing guard finds nothing to commit, and a
no-op run ends silently -- which is what "the badge is already correct"
should have looked like all along.

These tests drive the workflow's embedded script directly. Asserting on
its source text would pass on a rewrite that reintroduced the bug, so the
script is extracted and executed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "version-badge.yml"


def extract_writer() -> str:
    """Pull the `Write docs/version.json` heredoc out of the workflow."""
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Write docs/version.json")
    body = text[start:]
    match = re.search(r"python3 <<'PYEOF'\n(?P<code>.*?)\n\s*PYEOF", body, re.S)
    assert match, (
        "could not find the embedded writer script; if the workflow was "
        "restructured, update this test rather than deleting it"
    )
    code = match.group("code")
    # The heredoc is indented inside the YAML `run:` block.
    lines = code.splitlines()
    indent = min(
        (len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()), default=0
    )
    return "\n".join(ln[indent:] for ln in lines) + "\n"


def run_writer(workdir: Path, tag: str, bare: str) -> dict:
    script = workdir / "_writer.py"
    script.write_text(extract_writer(), encoding="utf-8")
    (workdir / "docs").mkdir(exist_ok=True)
    # Inherit the real environment and add to it. A hand-built `env=` dict
    # stops CPython from starting on windows-latest (SYSTEMROOT goes
    # missing); tests/test_json_shape_v4_169_7.py enforces that rule and
    # caught this file before CI did.
    env = {**os.environ, "VERSION_TAG": tag, "VERSION_BARE": bare}
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, f"writer failed:\n{result.stderr}"
    return json.loads((workdir / "docs" / "version.json").read_text(encoding="utf-8"))


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    return tmp_path


def test_rerun_at_same_version_is_byte_identical(workdir: Path) -> None:
    """The actual bug: a second run must leave nothing to commit."""
    run_writer(workdir, "v4.169.30", "4.169.30")
    first = (workdir / "docs" / "version.json").read_bytes()

    time.sleep(1.1)  # guarantee a different wall-clock second
    run_writer(workdir, "v4.169.30", "4.169.30")
    second = (workdir / "docs" / "version.json").read_bytes()

    assert first == second, (
        "version.json changed on a re-run at the same version; the badge bot "
        "will commit again, which is the 263-commit churn this fixes"
    )


def test_a_real_version_bump_still_updates_the_stamp(workdir: Path) -> None:
    """Silencing the churn must not silence the signal."""
    run_writer(workdir, "v4.169.30", "4.169.30")
    before = json.loads((workdir / "docs" / "version.json").read_text())

    time.sleep(1.1)
    after = run_writer(workdir, "v4.169.31", "4.169.31")

    assert after["tag_name"] == "v4.169.31"
    assert after["semver"] == "4.169.31"
    assert after["updated_at"] != before["updated_at"], (
        "a genuine release did not refresh updated_at"
    )


def test_first_ever_write_gets_a_stamp(workdir: Path) -> None:
    doc = run_writer(workdir, "v4.169.31", "4.169.31")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", doc["updated_at"])


def test_corrupt_existing_file_does_not_wedge_the_writer(workdir: Path) -> None:
    """Fail forward on garbage: rewrite it, do not crash the release job."""
    (workdir / "docs" / "version.json").write_text("{not json", encoding="utf-8")
    doc = run_writer(workdir, "v4.169.31", "4.169.31")
    assert doc["semver"] == "4.169.31"
    assert doc["updated_at"]


def test_partial_match_still_refreshes_the_stamp(workdir: Path) -> None:
    """tag and semver must BOTH match before a stamp is reused."""
    (workdir / "docs" / "version.json").write_text(
        json.dumps(
            {
                "tag_name": "v4.169.30",
                "semver": "4.169.29",  # disagrees with the tag
                "updated_at": "2020-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    doc = run_writer(workdir, "v4.169.30", "4.169.30")
    assert doc["updated_at"] != "2020-01-01T00:00:00Z", (
        "a stale stamp survived a version that did not fully match"
    )

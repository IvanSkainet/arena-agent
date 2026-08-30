"""AGENTS.md must not lie to the agent reading it.

Every new agent is told to start from AGENTS.md. When a number in it drifts
from the number the suite actually enforces, the document does not merely go
stale -- it actively misdirects. The instance that found this was told product
files must stay under 700 lines while the gate allowed 1600, which would have
meant splitting files to satisfy a limit that does not exist.

These tests read the enforced values out of the test modules themselves, so the
prose can only be verified against what the code does, never against another
piece of prose.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_MD = REPO_ROOT / "AGENTS.md"


def _load(rel: str):
    path = REPO_ROOT / rel
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader, f"cannot load {rel}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agents_text() -> str:
    return AGENTS_MD.read_text(encoding="utf-8")


def test_agents_md_exists_and_is_substantial(agents_text):
    """A detector that reads an empty file would pass forever."""
    assert len(agents_text.splitlines()) > 100, "AGENTS.md is suspiciously short"


@pytest.mark.parametrize(
    ("module_rel", "constant", "phrase_file"),
    [
        ("tests/test_project_modularity.py", "MAX_PRODUCT_FILE_LINES",
         "tests/test_project_modularity.py"),
        ("tests/test_architecture_boundaries.py", "MAX_RUNTIME_LINES",
         "tests/test_architecture_boundaries.py"),
    ],
)
def test_documented_line_limits_match_the_enforced_ones(
    agents_text, module_rel, constant, phrase_file
):
    """The number in the prose must be the number the gate enforces.

    Anchored on the referenced filename rather than on wording, so rephrasing
    the sentence cannot silently disable this check.
    """
    enforced = getattr(_load(module_rel), constant)
    pattern = re.escape(f"`{phrase_file}`") + r"[^)]*?\(\*\*currently (\d+) lines\*\*\)"
    match = re.search(pattern, agents_text, re.DOTALL)
    assert match, (
        f"AGENTS.md no longer states a limit for {phrase_file}; if the sentence "
        f"was rewritten, update this test so the claim stays verified"
    )
    documented = int(match.group(1))
    assert documented == enforced, (
        f"AGENTS.md says {phrase_file} enforces {documented} lines, but "
        f"{constant} is {enforced}. An agent following the document would "
        f"restructure code to satisfy a limit that does not exist."
    )


def test_every_repo_path_mentioned_in_agents_md_exists(agents_text):
    """A path that has moved sends the reader hunting for a file that is gone."""
    candidates = set(re.findall(r"`([A-Za-z0-9_./-]+\.(?:py|md|toml|yml|yaml))`", agents_text))
    missing = []
    for rel in sorted(candidates):
        if "/" not in rel:
            continue  # bare filenames are prose, not paths (e.g. `conftest.py`)
        if not (REPO_ROOT / rel).exists():
            missing.append(rel)
    assert missing == [], f"AGENTS.md references paths that do not exist: {missing}"

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


def _documented_limit(text: str, phrase_file: str):
    """The limit AGENTS.md claims for `phrase_file`, or None if it claims none."""
    pattern = re.escape(f"`{phrase_file}`") + r"[^)]*?\(\*\*currently (\d+) lines\*\*\)"
    match = re.search(pattern, text, re.DOTALL)
    return int(match.group(1)) if match else None


def _missing_paths(text: str) -> list[str]:
    """Repo paths cited in `text` that do not exist on disk."""
    candidates = set(re.findall(r"`([A-Za-z0-9_./-]+/[A-Za-z0-9_./-]*)`", text))
    missing = []
    for rel in sorted(candidates):
        cleaned = rel.rstrip("/")
        # Absolute paths are host locations (/tmp/...), HTTP routes
        # (/v1/exec/script) or API endpoints -- not files in this checkout.
        if not cleaned or cleaned.startswith("/") or cleaned.endswith("*"):
            continue
        # `owner/repo` GitHub slugs are not paths either.
        top = cleaned.split("/", 1)[0]
        if not (REPO_ROOT / top).exists():
            continue
        if not (REPO_ROOT / cleaned).exists():
            missing.append(cleaned)
    return missing


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
    documented = _documented_limit(agents_text, phrase_file)
    assert documented is not None, (
        f"AGENTS.md no longer states a limit for {phrase_file}; if the sentence "
        f"was rewritten, update this test so the claim stays verified"
    )
    assert documented == enforced, (
        f"AGENTS.md says {phrase_file} enforces {documented} lines, but "
        f"{constant} is {enforced}. An agent following the document would "
        f"restructure code to satisfy a limit that does not exist."
    )


def test_every_repo_path_mentioned_in_agents_md_exists(agents_text):
    """A path that has moved sends the reader hunting for a file that is gone.

    Covers extensionless references (`bin/arena-relay`) and directories
    (`scripts/`) too: restricting this to five extensions let those rot while
    the gate stayed green.
    """
    missing = _missing_paths(agents_text)
    assert missing == [], f"AGENTS.md references paths that do not exist: {missing}"


def test_the_path_gate_rejects_a_path_that_does_not_exist():
    """Negative test: the failure branch must actually fire."""
    bogus = "`arena/definitely_not_here/nope.py`"
    assert _missing_paths(f"see {bogus} for details") == [
        "arena/definitely_not_here/nope.py"
    ], "the path gate accepted a citation of a file that does not exist"


def test_the_path_gate_accepts_extensionless_and_directory_paths():
    """Real references that must not be reported as missing."""
    assert _missing_paths("`scripts/` and `tests/`") == []


def test_the_line_limit_gate_rejects_a_documented_value_that_disagrees(tmp_path):
    """Negative test for the line-limit gate, committed rather than manual.

    Feeds the checker prose claiming a limit the code does not enforce and
    asserts it objects, so the comparison cannot silently become a no-op.
    """
    enforced = getattr(_load("tests/test_project_modularity.py"), "MAX_PRODUCT_FILE_LINES")
    wrong = enforced + 137
    text = (
        f"Product files must stay under the limit enforced by "
        f"`tests/test_project_modularity.py` (**currently {wrong} lines**)."
    )
    documented = _documented_limit(text, "tests/test_project_modularity.py")
    assert documented == wrong
    assert documented != enforced, (
        "fixture is not actually a mismatch; the negative test proves nothing"
    )


def test_the_line_limit_gate_rejects_a_missing_claim():
    """If the sentence is deleted or rewritten, the gate must notice."""
    assert _documented_limit("nothing about limits here", "tests/test_project_modularity.py") is None

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


TASK_BOARD = REPO_ROOT / "docs" / "TASK_BOARD.md"


def _completed_tasks() -> set[str]:
    """Task ids the board marks done, as `- [x] **T57 ...`."""
    text = TASK_BOARD.read_text(encoding="utf-8")
    return {m.group(2) for m in re.finditer(r"^- \[([ x])\] \*\*(T\d+)\b", text, re.M)
            if m.group(1) == "x"}


def _cited_tasks(text: str) -> set[str]:
    return {f"T{n}" for n in re.findall(r"\bT(\d+)\b", text)}


def _stale_citations(text: str) -> list[str]:
    """Task ids `text` cites that the board marks complete.

    The gate and its negative test share this so the test exercises the
    real decision. Asserting only that the two parser helpers behave
    leaves the gate itself untested: it can be reduced to `stale = []`
    and the suite stays green. (Caught in review on #234 -- worth
    recording, because the original sabotage pass mutated the parser and
    missed it.)
    """
    return sorted(_cited_tasks(text) & _completed_tasks())


def test_agents_md_does_not_direct_work_at_finished_tasks(agents_text):
    """The document must not send an agent at work that is already done.

    This is the failure the numeric gates could not see. AGENTS.md opened
    with "finish T57 Dependabot relock acceptance, then T58", and T57 had
    been closed on the board for three releases. Every path it cited
    existed and every limit it quoted was right, so the suite stayed
    green while the first instruction a new agent read was false.

    Wrong prose is worse than missing prose here: an agent that cannot
    find guidance asks, while an agent handed a confident stale
    instruction goes and does it.

    The rule is deliberately blunt -- do not name a completed task id at
    all, not even historically. An "it's only a historical mention"
    exemption is exactly the sort of carve-out that grows until the gate
    means nothing. Refer to `docs/TASK_BOARD.md`, which is the one place
    task state is tracked.
    """
    stale = _stale_citations(agents_text)
    assert not stale, (
        f"AGENTS.md cites tasks the board marks complete: {stale}. "
        "Point at docs/TASK_BOARD.md instead of naming task ids."
    )


def test_the_task_state_gate_rejects_a_citation_of_a_finished_task():
    """Negative test: the failure branch must actually fire.

    Uses a task the board really does mark done, so the test fails if
    the parser stops recognising the board's format -- a silent no-op
    would otherwise look identical to a clean repository.
    """
    done = _completed_tasks()
    assert done, "no completed tasks parsed from the board; the parser is broken"
    victim = sorted(done)[0]
    # Drive the same function the gate calls, not just its inputs.
    assert _stale_citations(f"first finish {victim} and then continue") == [victim]


def test_the_gate_actually_consults_the_stale_citation_check():
    """The gate must fail when handed prose citing finished work.

    Sharing a helper is not enough: `stale = []` inside the gate leaves
    every other test green, because they exercise the helper directly
    while the gate quietly stops calling it. So drive the gate itself
    with synthetic text and require it to object.

    This test exists because two rounds of sabotage missed that hole --
    the first mutated the parser, the second the helper, and neither
    touched the gate body. It was caught in review on #234.
    """
    done = _completed_tasks()
    assert done, "no completed tasks parsed from the board; the parser is broken"
    victim = sorted(done)[0]
    with pytest.raises(AssertionError, match=victim):
        test_agents_md_does_not_direct_work_at_finished_tasks(
            f"Current sequence: finish {victim} before anything else."
        )


def test_the_task_state_gate_ignores_open_tasks():
    """Naming work that is still open is legitimate and must stay allowed."""
    text = TASK_BOARD.read_text(encoding="utf-8")
    open_tasks = {m.group(2) for m in re.finditer(r"^- \[([ x])\] \*\*(T\d+)\b", text, re.M)
                  if m.group(1) == " "}
    assert open_tasks, "no open tasks parsed from the board; the parser is broken"
    victim = sorted(open_tasks)[0]
    assert _stale_citations(f"continue with {victim}") == []


def _invoked_scripts(text: str) -> set[str]:
    """Repo-relative script paths the document tells the reader to run."""
    return set(re.findall(r"python3?\s+(scripts/[\w./-]+\.py)", text))


def _missing_scripts(text: str) -> list[str]:
    """Invoked scripts that do not exist. Shared so the negative tests
    exercise the same decision the gate makes."""
    return sorted(rel for rel in _invoked_scripts(text)
                  if not (REPO_ROOT / rel).is_file())


def test_documented_gate_scripts_exist(agents_text):
    """Every `python scripts/X.py` the document tells you to run must exist.

    AGENTS.md is the first thing a new agent reads, so a command that
    cannot run is worse than no command: it gets copied, fails oddly,
    and the reader concludes the whole document is stale.

    This is the cheap half of the problem. The expensive half was a
    claim that the analyzers behind `quality_ratchet.py` could not be
    installed locally and that findings like `bad-assignment` were
    CI-only. That was false -- measured on #239 after it had already
    cost a push-and-wait cycle -- and no gate could have caught it,
    because the sentence named no path and quoted no number. Prose that
    asserts a *capability* is the residual risk here; keep such claims
    falsifiable, and prefer a command a reader can run over an assertion
    about what is possible.
    """
    invoked = _invoked_scripts(agents_text)
    assert invoked, "AGENTS.md no longer invokes any script; update this test"
    missing = _missing_scripts(agents_text)
    assert not missing, (
        f"AGENTS.md tells the reader to run scripts that do not exist: {missing}"
    )


def test_the_script_gate_rejects_a_command_that_cannot_run():
    """Negative test, driven by synthetic prose.

    Sabotage caught the need for this: with every real script present,
    stubbing the check to `missing = []` was indistinguishable from the
    genuine one and the suite stayed green. Same hole as #234 -- assert
    on the decision, not on a repository that happens to be clean.
    """
    text = "run `python scripts/definitely_not_here.py` to continue"
    assert _missing_scripts(text) == ["scripts/definitely_not_here.py"]


def test_the_script_gate_actually_consults_the_check():
    """The gate must object when handed prose naming a missing script.

    Sharing a helper is not enough: `missing = []` inside the gate keeps
    every other test green, because they call the helper directly while
    the gate quietly stops using it. This drives the gate itself.

    Exactly the hole found in review on #234, hit again here -- which is
    why it is now a fixed step rather than something to remember.
    """
    with pytest.raises(AssertionError, match="scripts/definitely_not_here.py"):
        test_documented_gate_scripts_exist(
            "run `python scripts/definitely_not_here.py` first"
        )


def test_the_script_gate_accepts_a_command_that_can():
    """And must not cry wolf on a script that exists."""
    assert _missing_scripts("run `python scripts/quality_ratchet.py`") == []


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

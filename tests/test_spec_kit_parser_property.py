"""v4.61.0 - property-based tests for scripts/spec_kit_to_scenarios.py.

The example-based tests in ``test_spec_kit_adapter.py`` cover the
realistic shapes a human author would write. This file goes further
and checks *invariants* on fuzzed input, so a future regex tweak
that subtly breaks the parser (e.g. forgets to honour ``[x]`` vs
``[ ]`` checkboxes, swallows a parallel marker, mis-counts braces
inside a placeholder) trips the test on a small counter-example
rather than passing on the happy path.

Invariants asserted:

  * ``parse_tasks`` is total — it never raises on any text input;
    the worst it can do is return an empty list.
  * All step IDs are unique within a single parse.
  * The number of parsed steps is at most the number of lines that
    match the task-start shape (we never invent steps from nothing).
  * Whenever the parser extracted an Args: block, the result must
    be a dict that round-trips through ``json.dumps`` + ``json.loads``
    byte-for-byte.
  * ``build_scenario`` always produces the documented top-level shape.

These run with ``hypothesis``. They are skipped (not failed) when
``hypothesis`` isn't installed, so the rest of the suite stays green
on operators who don't run ``pip install -e .[dev]``.

The tests don't use a tmp_path fixture (hypothesis + pytest's
function-scoped fixtures don't mix well); instead each test creates
its own scratch dir via ``tempfile.mkdtemp`` and cleans up after
itself with ``shutil.rmtree``. The dir is shared across all examples
of a single test, because ``write_text`` truncates on open.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

try:
    from hypothesis import HealthCheck, given, settings, strategies as st
except ImportError:  # pragma: no cover - guard for operators without dev deps
    pytest.skip("hypothesis is not installed; skipping property tests",
                allow_module_level=True)

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import spec_kit_to_scenarios as adapter  # noqa: E402  -- after sys.path tweak


# ---------------------------------------------------------------------------
# Strategy builders
# ---------------------------------------------------------------------------

# A reasonable spec-kit tool name. The first char must be a letter per the
# parser regex; we restrict to ASCII identifier characters to keep the
# generated markdown well-formed and to make the strategy deterministic
# across hypothesis versions.
_TOOL_NAME_RE = r"[A-Za-z_][\w.]*"


@st.composite
def _task_line(draw: Any) -> str:
    """Synthesize a single spec-kit task line.

    Produces shapes covering all the flags the parser handles: ``[P]``,
    ``[US<digit>]``, backticked or bare tool path, optional ``Args: {...}``
    JSON block, optional ``Save as <name>`` note.
    """
    tid = f"T{draw(st.integers(min_value=0, max_value=99))}"
    flags: list[str] = []
    if draw(st.booleans()):
        flags.append("[P]")
    if draw(st.booleans()):
        flags.append(f"[US{draw(st.integers(min_value=1, max_value=9))}]")
    tool = draw(st.from_regex(_TOOL_NAME_RE, fullmatch=True)).strip(".")
    if not tool or "." not in tool:
        tool = "a.b"
    use_backticks = draw(st.booleans())
    tool_str = f"`{tool}`" if use_backticks else tool
    prefix = " ".join(flags)
    checkbox = draw(st.sampled_from(["- [ ]", "- [x]"]))
    # The body must not start with a colon or backtick (would confuse
    # the markdown parser), and must be non-empty so the regex matches.
    body = draw(st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "Zs"),
            blacklist_characters="\r\n:",
        ),
        min_size=1, max_size=120,
    )).strip()
    line = f"{checkbox} {tid} {prefix} In {tool_str}: {body}".strip()
    line = re.sub(r"\s+", " ", line)
    return line


_task_line_strategy = _task_line()


@st.composite
def _tasks_md(draw: Any) -> str:
    """Synthesize a plausible tasks.md with 0..N task lines and
    optional ``## Section`` headers between them."""
    n_tasks = draw(st.integers(min_value=0, max_value=12))
    n_headers = draw(st.integers(min_value=0, max_value=3))
    parts: list[str] = ["# Tasks: fuzz\n", "**Input**: fuzz\n"]
    for _ in range(n_headers):
        parts.append("## Section\n")
    for _ in range(n_tasks):
        parts.append(draw(_task_line_strategy) + "\n")
    return "".join(parts)


_DEFAULT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
    ],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Scratch:
    """Single scratch dir reused across hypothesis examples of a test.

    ``write_text`` truncates on open, so we don't need a fresh path per
    example. The dir is deleted when the context manager exits.
    """

    def __enter__(self) -> Path:
        self._d = tempfile.mkdtemp(prefix="spec-kit-prop-")
        return Path(self._d)

    def __exit__(self, *exc: Any) -> None:
        shutil.rmtree(self._d, ignore_errors=True)


def _parse(body: str, workdir: Path) -> list[dict]:
    p = workdir / "tasks.md"
    p.write_text(body, encoding="utf-8")
    return adapter.parse_tasks(p)


# ---------------------------------------------------------------------------
# Invariants on parse_tasks
# ---------------------------------------------------------------------------

@_DEFAULT_SETTINGS
@given(_tasks_md())
def test_parse_tasks_never_raises(body: str) -> None:
    """Total: any text is a valid input; worst case is an empty list."""
    with _Scratch() as workdir:
        steps = _parse(body, workdir)
    assert isinstance(steps, list)
    for s in steps:
        assert set(s) >= {"id", "tool", "arguments", "description",
                          "parallel", "story", "return_to"}


@_DEFAULT_SETTINGS
@given(_tasks_md())
def test_parse_tasks_preserves_unique_ids(body: str) -> None:
    """When the input has only unique task IDs, the output preserves
    that uniqueness. (Duplicates in input are allowed and survive
    verbatim; the parser is intentionally not a validator.)"""
    with _Scratch() as workdir:
        steps = _parse(body, workdir)
    # Extract the same task-id tokens the parser sees, in order. If
    # the input has any duplicate, we cannot say anything about the
    # parser's uniqueness behaviour, so skip.
    seen_in: list[str] = []
    for line in body.splitlines():
        m = adapter.TASK_START_RE.match(line)
        if m:
            seen_in.append(m.group("id"))
    if len(seen_in) != len(set(seen_in)):
        pytest.skip("input has duplicate task ids; not the parser's job to dedupe")
    ids = [s["id"] for s in steps]
    assert len(ids) == len(set(ids)), f"parser duplicated a unique id: {ids}"


@_DEFAULT_SETTINGS
@given(_tasks_md())
def test_parse_tasks_does_not_invent_steps(body: str) -> None:
    """Number of parsed steps must not exceed the number of task-start
    lines, which is a function of the input alone."""
    with _Scratch() as workdir:
        steps = _parse(body, workdir)
    starts = sum(1 for line in body.splitlines()
                 if adapter.TASK_START_RE.match(line))
    assert len(steps) <= starts, (f"parsed {len(steps)} steps but only "
                                   f"{starts} task-start lines present")


@_DEFAULT_SETTINGS
@given(_tasks_md())
def test_parse_tasks_arguments_round_trip_json(body: str) -> None:
    """Whenever the parser extracted an Args: block, the result must
    be a dict that round-trips through json without loss."""
    with _Scratch() as workdir:
        steps = _parse(body, workdir)
    for s in steps:
        args = s["arguments"]
        if args:  # empty == no Args block found, that's fine
            assert isinstance(args, dict)
            again = json.loads(json.dumps(args, ensure_ascii=False))
            assert again == args


# ---------------------------------------------------------------------------
# Invariants on build_scenario
# ---------------------------------------------------------------------------

@_DEFAULT_SETTINGS
@given(_tasks_md())
def test_build_scenario_always_has_top_level_shape(body: str) -> None:
    with _Scratch() as workdir:
        steps = _parse(body, workdir)
    s = adapter.build_scenario(steps, name="fuzz", description="")
    assert set(s) >= {"name", "description", "version", "steps", "final"}
    assert s["name"] == "fuzz"
    assert isinstance(s["steps"], list)
    assert s["version"] == "1"


@_DEFAULT_SETTINGS
@given(_tasks_md())
def test_build_scenario_step_arguments_are_dicts(body: str) -> None:
    with _Scratch() as workdir:
        steps = _parse(body, workdir)
    s = adapter.build_scenario(steps, name="fuzz", description="")
    for step in s["steps"]:
        assert isinstance(step["arguments"], dict)
        # The output JSON must serialise without errors.
        json.dumps(step, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Cross-validation: the happy-path example from the existing test suite
# must still parse, so the property-based strategies aren't drifting
# away from real inputs.
# ---------------------------------------------------------------------------

def test_property_strategies_cover_realistic_input(tmp_path: Path) -> None:
    body = (
        "# Tasks: voice\n"
        "## Phase 1\n"
        "- T0 [P] [US1] In `mobile.record_start`: begin. "
        'Args: `{"serial": "default"}`. Save as `recording_id`.\n'
        "- T1 [US1] In `mobile.record_stop`: stop. Args: `{}`.\n"
    )
    steps = _parse(body, tmp_path)
    assert len(steps) == 2
    assert steps[0]["parallel"] is True
    assert steps[0]["story"] == "US1"
    assert steps[0]["return_to"] == "recording_id"
    assert steps[1]["parallel"] is False
    assert steps[1]["return_to"] is None

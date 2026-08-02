"""E702 is at zero, and the splitter's narrowed guard still refuses correctly.

The E702 tool stalled at 112 rows for two releases, reporting them all as
"unsafe". The guard was over-broad: it treated *any* two statements of one
suite sharing a row as an inline suite, which also matches the ordinary

    home = tmp_path / "home"; home.mkdir()

inside a function body. What is actually dangerous is a suite sharing the row
with its **header** (`if c: a; b`), where splitting moves statements out of the
branch. Narrowing the test to that released 110 of the 112; the last two were a
multi-line string literal and were split by hand.

Both halves matter, so both are pinned here: the rule stays at zero, and the
guard still refuses a header-inline row rather than mangling it.

Green here does not mean the 112 rewrites behave identically -- that was
established by comparing compiled bytecode across 384 functions with NOP
padding, superinstruction fusion and jump renumbering normalised away, then by
executing the rewritten CLI modules.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLITTER = REPO / "scripts" / "e702_split_statements.py"

sys.path.insert(0, str(REPO / "scripts"))

import e702_split_statements as e702  # noqa: E402


def test_no_semicolon_joined_statements_remain():
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "E702",
         "--output-format=json", "arena", "tests"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode in (0, 1), proc.stderr
    hits = json.loads(proc.stdout or "[]")
    where = sorted(f"{h['filename']}:{h['location']['row']}" for h in hits)
    assert where == [], f"E702 came back at: {where[:20]}"


def test_splitter_reports_nothing_left():
    proc = subprocess.run([sys.executable, str(SPLITTER), "--check"],
                          cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 statements split, 0 left as debt" in proc.stdout, proc.stdout


# ---------------------------------------------------------------------------
# The narrowed guard: refuse header-inline, allow plain sequences
# ---------------------------------------------------------------------------

def _unsafe(src: str) -> set[int]:
    # Pass the source text, exactly as rewrite() does: `else`/`except`/
    # `finally` carry no lineno of their own, so the guard needs the physical
    # line to recognise a suite laid out inline with its keyword.
    return e702.unsafe_rows(ast.parse(src), src.splitlines())


def test_plain_two_statement_row_is_considered_safe():
    """The false refusal that stalled 112 rows for two releases."""
    src = "def f(tmp_path):\n    home = tmp_path / 'h'; home.mkdir()\n"
    assert 2 not in _unsafe(src)


def test_header_inline_row_is_still_refused():
    """`if c: a; b` must stay untouched -- splitting moves b out of the branch."""
    src = "def f(c):\n    if c: a(); b()\n"
    assert 2 in _unsafe(src)


def test_else_inline_row_is_still_refused():
    src = "def f(c):\n    if c:\n        a()\n    else: b(); c2()\n"
    assert 4 in _unsafe(src)


def test_except_inline_row_is_still_refused():
    src = "def f():\n    try:\n        a()\n    except Exception: b(); c()\n"
    assert 4 in _unsafe(src)


def test_multiline_statement_marks_every_row_it_covers():
    src = (
        "def f():\n"
        "    out.write(('''x\n"
        "y\n"
        "''').strip()); print(1)\n"
    )
    unsafe = _unsafe(src)
    assert {2, 3, 4} <= unsafe


def test_a_split_preserves_the_ast_and_behaviour(tmp_path):
    src = (
        "def f(xs):\n"
        "    out = []; n = 0\n"
        "    for x in xs:\n"
        "        out.append(x); n += 1\n"
        "    return out, n\n"
    )
    path = tmp_path / "m.py"
    path.write_text(src, encoding="utf-8")
    before = ast.dump(ast.parse(src), include_attributes=False)

    new_src, split, _ = e702.rewrite(src)
    assert split >= 2, split
    assert ast.dump(ast.parse(new_src), include_attributes=False) == before

    ns_old: dict = {}
    ns_new: dict = {}
    exec(compile(src, "old", "exec"), ns_old)
    exec(compile(new_src, "new", "exec"), ns_new)
    assert ns_old["f"]([1, 2, 3]) == ns_new["f"]([1, 2, 3]) == ([1, 2, 3], 3)


def test_header_inline_row_survives_a_rewrite_untouched():
    """End to end: the dangerous shape must come out byte-identical."""
    src = "def f(c):\n    if c: a(); b()\n    return 1\n"
    new_src, split, skipped = e702.rewrite(src)
    assert new_src == src, new_src
    assert split == 0 and skipped >= 1

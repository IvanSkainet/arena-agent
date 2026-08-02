"""The E701 splitter, and the floor it established.

Two jobs:

  1. Keep `arena/` and `tests/` at **zero** inline compound statements. The
     193 sites are gone; the ratchet would only notice *growth past 1772*, so
     E701 specifically could creep back one line at a time. This pins it at 0.

  2. Prove the transform itself on cases where a naive edit silently changes
     behaviour -- above all `else: a; b`, where dropping the trailing statement
     one indent too far moves it *out of the branch*.

Green here does not mean the 193 rewritten sites behave identically; that was
established separately by comparing compiled bytecode function-by-function
(377 functions, 0 differences after normalising three documented CPython
artifacts: __firstlineno__, NOP line-tracking padding, and superinstruction
fusion). This file guards the floor and the tool going forward.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPLITTER = REPO / "scripts" / "e701_split_compounds.py"

sys.path.insert(0, str(REPO / "scripts"))

import e701_split_compounds as e701  # noqa: E402

# ---------------------------------------------------------------------------
# The floor
# ---------------------------------------------------------------------------

def test_no_inline_compound_statements_remain():
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "E701",
         "--output-format=json", "arena", "tests"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode in (0, 1), proc.stderr
    hits = json.loads(proc.stdout or "[]")
    where = sorted(f"{h['filename']}:{h['location']['row']}" for h in hits)
    assert where == [], f"E701 came back at: {where[:20]}"


def test_splitter_reports_nothing_left_to_do():
    """`--check` is a report, so rc 0 alone proves nothing -- read the text.

    The tool exits non-zero only when the AST proof rejects a rewrite; a
    pending-but-splittable site still exits 0. Asserting on rc here would be a
    green light that means nothing, which is precisely the failure mode
    AGENTS.md warns about.
    """
    proc = subprocess.run([sys.executable, str(SPLITTER), "--check"],
                          cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "nothing to do" in proc.stdout, proc.stdout


# ---------------------------------------------------------------------------
# The transform, on the cases that actually bite
# ---------------------------------------------------------------------------

def _rewrite(line: str) -> list[str] | None:
    """Run one physical line through the splitter's row rewriter."""
    src = line + "\n"
    by_row, _ = e701._row_tokens(src)
    return e701.rewrite_row(line, by_row.get(1, []))


def test_else_with_two_statements_keeps_both_inside_the_branch():
    """The killer case. Both statements must land under `else:`."""
    out = _rewrite("    else: j({'ok': False}); sys.exit(1)")
    assert out == [
        "    else:",
        "        j({'ok': False})",
        "        sys.exit(1)",
    ]


def test_if_with_two_statements_keeps_both_inside_the_branch():
    out = _rewrite("if not ok: log('no'); return 1")
    assert out == ["if not ok:", "    log('no')", "    return 1"]


@pytest.mark.parametrize("line,head", [
    ("try: risky()", "try:"),
    ("except Exception: pass", "except Exception:"),
    ("finally: cleanup()", "finally:"),
    ("with LOCK: n = len(S)", "with LOCK:"),
    ("for x in xs: out.append(x)", "for x in xs:"),
    ("while go: tick()", "while go:"),
    ("class _R: pass", "class _R:"),
])
def test_every_compound_keyword_splits_at_its_header(line, head):
    out = _rewrite(line)
    assert out is not None and out[0] == head
    assert all(chunk.startswith("    ") for chunk in out[1:])


def test_bracketed_lambda_colon_is_not_mistaken_for_a_header():
    out = _rewrite("if f(lambda x: x + 1): go()")
    assert out == ["if f(lambda x: x + 1):", "    go()"]


def test_unbracketed_lambda_colon_at_depth_zero_is_not_the_header():
    """The case bracket-depth alone cannot solve.

    `if lambda: 1: go()` is legal Python: the lambda's colon sits at depth 0
    and comes *before* the header colon. Cutting at the first depth-0 colon
    would produce `if lambda:` -- a syntax error. Only the lambda counter
    saves this, so it is asserted separately from the bracketed case.
    """
    line = "if lambda: 1: go()"
    out = _rewrite(line)
    assert out == ["if lambda: 1:", "    go()"]
    # And the split must still mean the same thing.
    assert (ast.dump(ast.parse("\n".join(out)), include_attributes=False)
            == ast.dump(ast.parse(line), include_attributes=False))


def test_dict_and_slice_colons_are_not_headers():
    out = _rewrite("if d {'a': 1}: pass".replace(" {", "== {"))
    assert out is not None and out[0].endswith("}:")
    out2 = _rewrite("if xs[1:2]: pass")
    assert out2 == ["if xs[1:2]:", "    pass"]


def test_annotated_walrus_and_nested_brackets_survive():
    out = _rewrite("if (n := len(a[1:3])) > 0: use(n)")
    assert out == ["if (n := len(a[1:3])) > 0:", "    use(n)"]


def test_trailing_comment_follows_the_last_statement():
    out = _rewrite("if x: go()  # nosec B101")
    assert out == ["if x:", "    go()  # nosec B101"]


def test_tab_indented_line_keeps_tabs():
    out = _rewrite("\tif x: go()")
    assert out == ["\tif x:", "\t\tgo()"]


def test_already_split_header_is_left_alone():
    assert _rewrite("if x:") is None


def test_non_compound_line_is_refused():
    assert _rewrite("d = {'a': 1}") is None


# ---------------------------------------------------------------------------
# The safety proof itself
# ---------------------------------------------------------------------------

def test_rewrites_preserve_the_ast_on_a_synthetic_module(tmp_path):
    src = (
        "def f(xs, out):\n"
        "    if not xs: return 0\n"
        "    for x in xs:\n"
        "        try: out.append(x)\n"
        "        except Exception: pass\n"
        "    else: out.append('done'); return 1\n"
        "    return 2\n"
    )
    path = tmp_path / "m.py"
    path.write_text(src, encoding="utf-8")
    before = ast.dump(ast.parse(src), include_attributes=False)

    rows = {2, 4, 5, 6}
    done, skipped, notes = e701.process_file(path, rows, apply=True)
    assert done == len(rows), (done, skipped, notes)

    after_src = path.read_text(encoding="utf-8")
    assert ast.dump(ast.parse(after_src), include_attributes=False) == before
    assert "else:\n" in after_src

    ns_old: dict = {}
    ns_new: dict = {}
    exec(compile(src, "old", "exec"), ns_old)
    exec(compile(after_src, "new", "exec"), ns_new)
    out_old: list = []
    out_new: list = []
    assert ns_old["f"]([1, 2], out_old) == ns_new["f"]([1, 2], out_new)
    assert out_old == out_new


def test_a_rewrite_that_would_change_the_ast_is_refused(tmp_path, monkeypatch):
    """Sabotage the rewriter; the AST proof must reject and not write."""
    src = "def f(x):\n    if x: return 1\n    return 0\n"
    path = tmp_path / "m.py"
    path.write_text(src, encoding="utf-8")

    def evil(line, tokens):
        # Dedent the body out of the branch -- a real behaviour change.
        return ["    if x:", "        pass", "    return 1"]

    monkeypatch.setattr(e701, "rewrite_row", evil)
    done, _, notes = e701.process_file(path, {2}, apply=True)
    assert done == 0
    assert any("REJECTED" in n for n in notes), notes
    assert path.read_text(encoding="utf-8") == src, "file was modified despite rejection"

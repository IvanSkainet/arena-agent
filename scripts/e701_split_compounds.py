#!/usr/bin/env python3
"""Move inline compound-statement bodies onto their own lines (ruff E701).

Companion to ``scripts/e702_split_statements.py``, which deliberately skipped
these rows: ``if x: a; b`` is not a semicolon split, it is an indentation
decision, and getting it wrong silently moves statements *out of* the branch.

Why a tool and not hand edits: 194 sites, and AGENTS.md records that editing by
bare text already broke live code once (identical lines in different
functions). Why a tool and not ``ruff format``: that rewrites the whole tree
into an unreviewable diff.

The safety argument is the same one E702 used, and it is not "the tests pass":

  * the transform is purely mechanical (split a physical line at the header
    colon, re-indent the trailing simple statements one level deeper);
  * every file is accepted only if its parsed AST is **identical before and
    after, ignoring position attributes** — a structural proof that no
    statement changed suite, order, or nesting.

Rows are SKIPPED (left as debt) whenever safety is not provable:

  * the logical line does not begin and end on that physical row (brackets or
    a backslash continuation) — physical-line surgery would corrupt it;
  * no header colon can be located at bracket depth 0 (lambda colons and
    dict/slice/annotation colons are excluded by depth and by lambda tracking);
  * the body after the colon is empty, or is itself a compound header;
  * the file's AST does not match after the rewrite — the file is restored and
    the mismatch reported loudly rather than committed.

Usage:
    python3 scripts/e701_split_compounds.py --check    # report only
    python3 scripts/e701_split_compounds.py --apply
    python3 scripts/e701_split_compounds.py --apply --paths arena/foo.py
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("arena", "tests")

# Keywords that may legally carry an inline suite.
COMPOUND_KEYWORDS = (
    "if", "elif", "else", "for", "while", "with", "try", "except", "finally",
    "def", "class", "async",
)


def ruff_e701_rows(paths: list[str]) -> dict[Path, set[int]]:
    """Ask ruff which rows it flags, so the tool and the gate agree."""
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "E701",
         "--output-format=json", *paths],
        cwd=ROOT, capture_output=True, text=True,
    )
    # Fail closed: rc 0 = clean, 1 = violations. Anything else is a broken
    # invocation and must not be read as "nothing to do".
    if proc.returncode not in (0, 1):
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(2)
    out: dict[Path, set[int]] = {}
    for item in json.loads(proc.stdout or "[]"):
        out.setdefault(Path(item["filename"]), set()).add(item["location"]["row"])
    return out


def _row_tokens(src: str) -> tuple[dict[int, list[tokenize.TokenInfo]], set[int]]:
    """Group tokens by starting row, and collect rows safe to slice.

    A row is "self-contained" when a logical line both starts and ends on it:
    the tokenizer emits its NEWLINE on the same row that the statement's first
    token appeared, and no token on the row spans into another row.
    """
    by_row: dict[int, list[tokenize.TokenInfo]] = {}
    self_contained: set[int] = set()
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return {}, set()

    logical_start: int | None = None
    spans_rows = False
    for tok in toks:
        if tok.type in (tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING):
            continue
        by_row.setdefault(tok.start[0], []).append(tok)
        if tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT):
            if tok.type == tokenize.NEWLINE:
                if logical_start is not None and not spans_rows:
                    self_contained.add(logical_start)
                logical_start = None
                spans_rows = False
            continue
        if logical_start is None:
            logical_start = tok.start[0]
        if tok.start[0] != tok.end[0] or tok.start[0] != logical_start:
            spans_rows = True
    return by_row, self_contained


def header_colon_col(tokens: list[tokenize.TokenInfo]) -> int | None:
    """Column of the colon that ends a compound header, or None.

    Depth tracking excludes dict/slice/annotation colons; an explicit lambda
    counter excludes ``lambda x: ...`` parameter colons, which sit at depth 0
    when the lambda is a bare argument.
    """
    if not tokens:
        return None
    first = tokens[0]
    if first.type != tokenize.NAME or first.string not in COMPOUND_KEYWORDS:
        return None

    depth = 0
    pending_lambdas = 0
    for tok in tokens:
        if tok.type == tokenize.OP:
            if tok.string in "([{":
                depth += 1
            elif tok.string in ")]}":
                depth -= 1
            elif tok.string == ":" and depth == 0:
                if pending_lambdas:
                    pending_lambdas -= 1
                    continue
                return tok.start[1]
        elif tok.type == tokenize.NAME and tok.string == "lambda" and depth == 0:
            pending_lambdas += 1
    return None


def split_simple_statements(body: str) -> list[str] | None:
    """Split a simple-statement list on top-level ';'. None if untokenizable."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(body).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    depth = 0
    cuts: list[int] = []
    for tok in toks:
        if tok.type != tokenize.OP:
            continue
        if tok.string in "([{":
            depth += 1
        elif tok.string in ")]}":
            depth -= 1
        elif tok.string == ";" and depth == 0:
            cuts.append(tok.start[1])
    parts: list[str] = []
    prev = 0
    for cut in cuts:
        parts.append(body[prev:cut])
        prev = cut + 1
    parts.append(body[prev:])
    cleaned = [p.strip() for p in parts]
    # A trailing ';' produces an empty tail; that is fine, drop it.
    cleaned = [p for p in cleaned if p]
    return cleaned or None


def _indent_unit(line: str) -> str:
    return "\t" if line[: len(line) - len(line.lstrip())].startswith("\t") else "    "


def rewrite_row(line: str, tokens: list[tokenize.TokenInfo]) -> list[str] | None:
    """Return replacement lines for one inline-suite row, or None to skip."""
    col = header_colon_col(tokens)
    if col is None:
        return None

    header = line[: col + 1]
    tail = line[col + 1:]
    if not tail.strip():
        return None  # already split; ruff would not have flagged it

    # A trailing comment belongs to the last moved statement, not the header.
    comment = ""
    for tok in tokens:
        if tok.type == tokenize.COMMENT and tok.start[1] > col:
            comment = line[tok.start[1]:].rstrip()
            tail = line[col + 1: tok.start[1]]
            break

    body = tail.strip()
    if not body:
        return None
    # Refuse nested compound headers (`if a: while b: ...` is invalid Python,
    # but a match/case or a future construct could surprise us).
    first_word = body.split(":")[0].split()[0] if body.split() else ""
    if first_word in COMPOUND_KEYWORDS and ":" in body:
        return None

    stmts = split_simple_statements(body)
    if not stmts:
        return None

    base = line[: len(line) - len(line.lstrip())]
    inner = base + _indent_unit(line)
    out = [header.rstrip()]
    for i, stmt in enumerate(stmts):
        suffix = f"  {comment}" if (comment and i == len(stmts) - 1) else ""
        out.append(f"{inner}{stmt}{suffix}")
    return out


def process_file(path: Path, rows: set[int], apply: bool) -> tuple[int, int, list[str]]:
    """Return (rewritten, skipped, notes) for one file."""
    src = path.read_text(encoding="utf-8")
    try:
        before = ast.dump(ast.parse(src), include_attributes=False)
    except SyntaxError as exc:
        return 0, len(rows), [f"{path}: unparseable before edit: {exc}"]

    by_row, self_contained = _row_tokens(src)
    if not by_row:
        return 0, len(rows), [f"{path}: could not tokenize"]

    lines = src.splitlines(keepends=True)
    notes: list[str] = []
    planned: dict[int, list[str]] = {}

    for row in sorted(rows):
        if row not in self_contained:
            notes.append(f"{path}:{row}: skipped (logical line spans rows)")
            continue
        raw = lines[row - 1]
        newline = "\n" if raw.endswith("\n") else ""
        replacement = rewrite_row(raw.rstrip("\n"), by_row.get(row, []))
        if replacement is None:
            notes.append(f"{path}:{row}: skipped (no provable split)")
            continue
        planned[row] = [chunk + newline for chunk in replacement]

    if not planned:
        return 0, len(rows), notes

    # Bottom-up so earlier row indices stay valid.
    new_lines = list(lines)
    for row in sorted(planned, reverse=True):
        new_lines[row - 1: row] = planned[row]
    new_src = "".join(new_lines)

    try:
        after = ast.dump(ast.parse(new_src), include_attributes=False)
    except SyntaxError as exc:
        return 0, len(rows), notes + [f"{path}: REJECTED, rewrite does not parse: {exc}"]
    if after != before:
        return 0, len(rows), notes + [f"{path}: REJECTED, AST changed — not written"]

    if apply:
        path.write_text(new_src, encoding="utf-8")
    return len(planned), len(rows) - len(planned), notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write changes")
    ap.add_argument("--check", action="store_true", help="report only (default)")
    ap.add_argument("--paths", nargs="*", default=list(TARGETS))
    args = ap.parse_args()
    apply = args.apply and not args.check

    found = ruff_e701_rows(args.paths)
    if not found:
        print("E701: nothing to do")
        return 0

    total_rows = sum(len(v) for v in found.values())
    rewritten = skipped = 0
    all_notes: list[str] = []
    for path in sorted(found):
        did, skip, notes = process_file(path, found[path], apply)
        rewritten += did
        skipped += skip
        all_notes.extend(notes)

    verb = "rewrote" if apply else "would rewrite"
    print(f"E701: {total_rows} flagged rows in {len(found)} files")
    print(f"  {verb}: {rewritten}")
    print(f"  skipped (left as debt): {skipped}")
    rejects = [n for n in all_notes if "REJECTED" in n]
    for note in all_notes[:40]:
        print("   ", note)
    if len(all_notes) > 40:
        print(f"    ... and {len(all_notes) - 40} more")
    # A rejection means the AST proof caught something; surface it as failure.
    return 1 if rejects else 0


if __name__ == "__main__":
    raise SystemExit(main())

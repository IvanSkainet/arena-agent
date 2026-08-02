#!/usr/bin/env python3
"""Split semicolon-joined statements (ruff E702) — AST-proven safe.

Why a tool and not a bulk formatter: `ruff format` would rewrite the whole
tree (huge unreviewable diff), and hand-editing 300+ sites invites the exact
mistake that already bit this repo once (identical source lines in different
functions, see AGENTS.md). So this transform is mechanical AND each file is
accepted only when the parsed AST is byte-identical before/after — a proof
that behaviour cannot have changed.

Rows are SKIPPED (left as debt) when splitting is not provably safe:
  * the row also opens a compound statement (`if x: a; b`) — that is E701
    territory and needs indentation decisions, not a split;
  * any statement starting on the row continues onto later rows (brackets),
    so physical-line splitting would corrupt it;
  * the file's AST does not match after the rewrite (should never happen —
    the file is restored and reported).

Usage:
    python3 scripts/e702_split_statements.py --check   # report only
    python3 scripts/e702_split_statements.py --apply
"""

from __future__ import annotations

import argparse
import ast
import io
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("arena", "tests")


def semicolon_rows(src: str) -> dict[int, list[int]]:
    """Map 1-based row -> sorted 0-based columns of statement-separator ';'.

    Semicolons inside strings are not OP tokens, and a ';' inside brackets is
    a syntax error, so every OP ';' the tokenizer yields is a real separator.
    """
    rows: dict[int, list[int]] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(src).readline)
        for tok in tokens:
            if tok.type == tokenize.OP and tok.string == ";":
                rows.setdefault(tok.start[0], []).append(tok.start[1])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return {}
    return {r: sorted(cols) for r, cols in rows.items()}


def unsafe_rows(tree: ast.AST) -> set[int]:
    """Rows we refuse to touch.

    A row is only safe when every statement sitting on it belongs to the SAME
    suite and that suite starts on its own line. The subtle killer (caught by
    the AST proof on the first run) is an inline suite whose header is on a
    different physical row than its body:

        else: j({...}); sys.exit(1)          # `else` has no lineno of its own
        if cond: a; b                        # body shares the header row

    Naively splitting those moves the trailing statements OUT of the branch —
    a real behaviour change. So instead of guessing from header linenos, mark
    a row unsafe whenever a suite (body/orelse/finalbody/handlers) begins on
    it while the suite's *own* statements do not span the row exclusively.
    """
    bad: set[int] = set()

    def mark_inline_suite(stmts: list[ast.stmt]) -> None:
        """A suite laid out inline starts and ends on one row -> unsafe row."""
        if not stmts:
            return
        first_row = getattr(stmts[0], "lineno", None)
        if first_row is None:
            return
        # Any suite whose first statement shares its row with another
        # statement of the same suite is an inline suite (`x: a; b`).
        if len(stmts) > 1 and getattr(stmts[1], "lineno", None) == first_row:
            bad.add(first_row)

    for node in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            suite = getattr(node, attr, None)
            if isinstance(suite, list) and suite and isinstance(suite[0], ast.stmt):
                mark_inline_suite(suite)
                # Inline suite attached to a compound header (`if c: a; b`)
                header = getattr(node, "lineno", None)
                if header is not None and getattr(suite[0], "lineno", None) == header:
                    bad.add(header)
        for handler in getattr(node, "handlers", []) or []:
            hbody = getattr(handler, "body", None)
            if isinstance(hbody, list) and hbody:
                mark_inline_suite(hbody)
                if getattr(hbody[0], "lineno", None) == getattr(handler, "lineno", None):
                    bad.add(handler.lineno)

        # Only SIMPLE statements matter here. Compound ones (def/if/for/try…)
        # legitimately span rows; using their range would blacklist the whole
        # file (first attempt did exactly that: 0 splits, 316 "unsafe").
        if isinstance(node, ast.stmt) and not hasattr(node, "body"):
            end = getattr(node, "end_lineno", node.lineno)
            if end != node.lineno:
                # A statement spanning rows makes EVERY row it covers unsafe,
                # not just its first: the closing row can also host the next
                # statement (`''').strip()); print(out)`), and splitting there
                # cuts the multi-row expression in half. Caught by the AST
                # proof on the second dry run.
                bad.update(range(node.lineno, end + 1))
    return bad


def rewrite(src: str) -> tuple[str, int, int]:
    """Return (new_src, split_count, skipped_count)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src, 0, 0

    rows = semicolon_rows(src)
    if not rows:
        return src, 0, 0

    blocked = unsafe_rows(tree)
    lines = src.splitlines(keepends=True)
    split_count = 0
    skipped = 0

    for row in sorted(rows, reverse=True):  # bottom-up keeps indices valid
        if row in blocked:
            skipped += len(rows[row])
            continue
        idx = row - 1
        if idx >= len(lines):
            skipped += len(rows[row])
            continue

        raw = lines[idx]
        newline = "\r\n" if raw.endswith("\r\n") else "\n" if raw.endswith("\n") else ""
        body = raw[: len(raw) - len(newline)]
        indent = body[: len(body) - len(body.lstrip())]

        pieces: list[str] = []
        prev = 0
        for col in rows[row]:
            pieces.append(body[prev:col])
            prev = col + 1
        pieces.append(body[prev:])

        cleaned = [p.strip() for p in pieces]
        cleaned = [p for p in cleaned if p]
        if len(cleaned) < 2:
            skipped += len(rows[row])
            continue

        lines[idx] = newline.join(indent + p for p in cleaned) + newline
        split_count += len(rows[row])

    return "".join(lines), split_count, skipped


def process(path: Path, apply: bool) -> tuple[int, int, bool]:
    src = path.read_text(encoding="utf-8")
    try:
        before = ast.dump(ast.parse(src))
    except SyntaxError:
        return 0, 0, False

    new_src, split_count, skipped = rewrite(src)
    if split_count == 0:
        return 0, skipped, True

    try:
        after = ast.dump(ast.parse(new_src))
    except SyntaxError:
        print(f"REJECTED (syntax): {path}", file=sys.stderr)
        return 0, skipped, False

    if before != after:
        print(f"REJECTED (AST differs): {path}", file=sys.stderr)
        return 0, skipped, False

    if apply:
        path.write_text(new_src, encoding="utf-8")
    return split_count, skipped, True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes")
    ap.add_argument("--check", action="store_true", help="report only (default)")
    args = ap.parse_args()
    apply = args.apply and not args.check

    total_split = total_skip = 0
    rejected: list[str] = []
    touched: list[str] = []

    for target in TARGETS:
        for path in sorted((ROOT / target).rglob("*.py")):
            split_count, skipped, ok = process(path, apply)
            total_split += split_count
            total_skip += skipped
            if not ok:
                rejected.append(str(path.relative_to(ROOT)))
            if split_count:
                touched.append(f"{split_count:4d}  {path.relative_to(ROOT)}")

    print(f"{'APPLIED' if apply else 'DRY-RUN'}: {total_split} statements split, "
          f"{total_skip} left as debt (unsafe rows), {len(touched)} files")
    for line in touched[:20]:
        print("  ", line)
    if len(touched) > 20:
        print(f"   ... and {len(touched) - 20} more files")
    if rejected:
        print("REJECTED FILES (AST proof failed):")
        for r in rejected:
            print("  ", r)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

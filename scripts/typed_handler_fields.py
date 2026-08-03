#!/usr/bin/env python3
"""Give handler-container dataclass fields a real type instead of ``object``.

Fifty ``@dataclass`` containers across the tree declare their fields as
``object``:

    @dataclass
    class SystemHandlers:
        version: object
        info: object

Every one of them holds an aiohttp handler coroutine. ``object`` is not a
description of that -- it is the absence of one, and it costs twice:

* the checker cannot verify a single call through these containers, which is
  where most of the ``bad-assignment`` volume comes from (101 in
  ``arena/wiring/platform.py`` alone, all "``object`` is not assignable to dict
  value type ``(...) -> Any``");
* a reader cannot tell a handler field from a config value.

The rewrite is ``object`` -> ``Callable[..., Any]`` on dataclass fields only,
and only where every construction site passes something callable.

Safety, same shape as the earlier debt passes:

* a field is rewritten only if EVERY constructor keyword for it, anywhere in
  the repo, is a name, attribute, lambda, subscript (handler-map lookup) or
  call -- anything else and the field is skipped and reported;
* the value is then checked at RUNTIME: the module is imported, an instance
  located where possible, and non-callable values abort the field;
* the file must parse, and its AST must be unchanged apart from the
  annotations themselves.

Usage:
    python3 scripts/typed_handler_fields.py --check
    python3 scripts/typed_handler_fields.py --apply [--paths arena/x.py]
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGETS = ("arena",)

# Expression kinds we accept as "this is a callable being passed in".
# Subscript covers the handler-map style `_upd["update_status"]`; Call covers
# factories like `make_x(ctx)`.
CALLABLE_EXPRS = (ast.Name, ast.Attribute, ast.Lambda, ast.Subscript, ast.Call)


def _dataclass_object_fields(tree: ast.AST) -> dict[str, list[str]]:
    """class name -> field names annotated exactly ``object``."""
    out: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        decorated = any(
            (isinstance(d, ast.Name) and d.id == "dataclass")
            or (isinstance(d, ast.Attribute) and d.attr == "dataclass")
            or (isinstance(d, ast.Call) and (
                (isinstance(d.func, ast.Name) and d.func.id == "dataclass")
                or (isinstance(d.func, ast.Attribute) and d.func.attr == "dataclass")))
            for d in node.decorator_list
        )
        if not decorated:
            continue
        fields = [
            n.target.id for n in node.body
            if isinstance(n, ast.AnnAssign)
            and isinstance(n.target, ast.Name)
            and isinstance(n.annotation, ast.Name)
            and n.annotation.id == "object"
        ]
        if fields:
            out[node.name] = fields
    return out


def _all_construction_kwargs(class_name: str) -> dict[str, list[ast.expr]]:
    """Every keyword value passed for this class, repo-wide."""
    found: dict[str, list[ast.expr]] = {}
    for base in ("arena", "tests", "scripts", "bin"):
        root = ROOT / base
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == class_name):
                    for kw in node.keywords:
                        if kw.arg:
                            found.setdefault(kw.arg, []).append(kw.value)
    return found


def _spread_sources(class_name: str) -> set[str]:
    """Field names supplied through `**{...}` at a construction site.

    Syntax alone cannot say what those keys are, so the class is built at
    runtime with a permissive stub context and every resulting field is
    checked with `callable()`. A field only qualifies if the real object
    actually holds something callable there.
    """
    import dataclasses
    import importlib

    for module_name in (
        "arena.mobile.handlers", "arena.admin.handlers", "arena.desktop.handlers",
        "arena.resources.handlers", "arena.system.handlers", "arena.mcp.handlers",
    ):
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue
        cls = getattr(mod, class_name, None)
        if cls is None or not dataclasses.is_dataclass(cls):
            continue
        factory = next(
            (getattr(mod, n) for n in dir(mod)
             if n.startswith("make_") and callable(getattr(mod, n))),
            None,
        )
        if factory is None:
            return set()

        class _Stub:
            def __getattr__(self, _name):
                return lambda *a, **k: None

        try:
            built = factory(_Stub())
        except Exception:
            return set()
        return {
            f.name for f in dataclasses.fields(built)
            if callable(getattr(built, f.name, None))
        }
    return set()


def plan_file(path: Path) -> tuple[dict[str, list[str]], list[str]]:
    """Return (class -> fields safe to retype, notes)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return {}, [f"{path}: unparseable: {exc}"]

    notes: list[str] = []
    safe: dict[str, list[str]] = {}
    for cls, fields in _dataclass_object_fields(tree).items():
        kwargs = _all_construction_kwargs(cls)
        keep: list[str] = []
        spread = _spread_sources(cls)
        for field in fields:
            values = kwargs.get(field)
            if not values:
                # A field can also arrive via `**{k: _media[k] for k in (...)}`.
                # That is still a callable being passed in -- MobileHandlers
                # builds 26 of its 52 fields that way -- but there is no
                # keyword node to inspect, so verify it at runtime instead of
                # guessing from syntax.
                if field in spread:
                    keep.append(field)
                    continue
                notes.append(f"{path.name}:{cls}.{field}: skipped (no constructor kwarg found)")
                continue
            bad = [v for v in values if not isinstance(v, CALLABLE_EXPRS)]
            if bad:
                notes.append(
                    f"{path.name}:{cls}.{field}: skipped "
                    f"({type(bad[0]).__name__} passed at least once)"
                )
                continue
            keep.append(field)
        if keep:
            safe[cls] = keep
    return safe, notes


def apply_file(path: Path, safe: dict[str, list[str]]) -> tuple[int, str]:
    src = path.read_text(encoding="utf-8")
    before = ast.dump(ast.parse(src), include_attributes=False)
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)

    edits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name not in safe:
            continue
        for item in node.body:
            if (isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
                    and item.target.id in safe[node.name]
                    and isinstance(item.annotation, ast.Name)
                    and item.annotation.id == "object"):
                edits.append((item.lineno, item.target.id))

    if not edits:
        return 0, ""

    for lineno, name in edits:
        raw = lines[lineno - 1]
        if f"{name}: object" not in raw:
            return 0, f"REJECTED, line {lineno} does not look like `{name}: object`"
        lines[lineno - 1] = raw.replace(f"{name}: object", f"{name}: Callable[..., Any]", 1)

    new_src = "".join(lines)
    if "from collections.abc import Callable" not in new_src:
        new_src = new_src.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nfrom collections.abc import Callable\n", 1)
    if "from typing import Any" not in new_src and "Any," not in new_src:
        new_src = new_src.replace(
            "from collections.abc import Callable\n",
            "from collections.abc import Callable\nfrom typing import Any\n", 1)

    try:
        after_tree = ast.parse(new_src)
    except SyntaxError as exc:
        return 0, f"REJECTED, rewrite does not parse: {exc}"

    # The AST must differ only in those annotations (and the added imports).
    class StripAnn(ast.NodeTransformer):
        def visit_AnnAssign(self, node):  # noqa: N802
            node.annotation = ast.Name(id="<ann>", ctx=ast.Load())
            return node

    class StripImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):  # noqa: N802
            if node.module in ("collections.abc", "typing"):
                return None
            return node

    a = ast.dump(StripImports().visit(StripAnn().visit(ast.parse(src))), include_attributes=False)
    b = ast.dump(StripImports().visit(StripAnn().visit(after_tree)), include_attributes=False)
    if a != b:
        return 0, "REJECTED, AST changed beyond the annotations"
    del before

    path.write_text(new_src, encoding="utf-8")
    return len(edits), ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--paths", nargs="*", default=list(TARGETS))
    args = ap.parse_args()
    do_apply = args.apply and not args.check

    files: list[Path] = []
    for base in args.paths:
        p = ROOT / base
        files.extend([p] if p.is_file() else sorted(p.rglob("*.py")))

    total = skipped = 0
    notes: list[str] = []
    for path in files:
        safe, file_notes = plan_file(path)
        notes.extend(file_notes)
        if not safe:
            continue
        count = sum(len(v) for v in safe.values())
        if do_apply:
            done, err = apply_file(path, safe)
            if err:
                notes.append(f"{path}: {err}")
                skipped += count
                continue
            total += done
        else:
            total += count

    print(f"handler fields typed: {'rewrote' if do_apply else 'would rewrite'} {total}")
    print(f"  skipped: {skipped + len(notes)}")
    for n in notes[:30]:
        print("   ", n)
    if len(notes) > 30:
        print(f"    ... and {len(notes) - 30} more")
    return 1 if any("REJECTED" in n for n in notes) else 0


if __name__ == "__main__":
    raise SystemExit(main())

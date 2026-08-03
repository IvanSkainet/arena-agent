#!/usr/bin/env python3
"""Declare what each mixin requires from the class that mixes it in.

`arena/browser/cdp_client/` is built from mixins: `CDPTab` is
`CDPTabConnectionMixin + CDPTabOpsMixin`, `CDPTabManager` composes seven more.
Each mixin freely reads `self._tabs`, `self.port`, `self._browser_ws` -- state
the *concrete* class owns. Nothing declares that requirement, so a checker sees
251 attribute accesses on classes that do not define them, and a reader has to
reconstruct the contract by grepping siblings.

These are not bugs. They are an undeclared interface, and an undeclared
interface is exactly the thing that lets a real typo hide among 251 shrugs.

This tool writes the contract down:

    class CDPTabOpsMixin:
        if TYPE_CHECKING:  # pragma: no cover - typing only
            _browser: CDPBrowser | None
            target_id: str
            async def get_title(self, ...) -> str | None: ...

Types are never invented. Each attribute is resolved from the concrete class
that actually defines it:

  * instance attributes -> the annotation on the concrete class, or the
    inferred type of its `__init__` assignment;
  * methods -> the sibling's real signature, copied verbatim including
    `async`, defaults and return type.

Anything that cannot be resolved that way is skipped and reported, never
guessed -- a wrong stub is worse than no stub, which this project already
learned when an approximate `get_title` stub produced two `not-async` and two
`inconsistent-inheritance` errors of its own.

Usage:
    python3 scripts/mixin_interface_decls.py --check
    python3 scripts/mixin_interface_decls.py --apply
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PACKAGE = "arena/browser/cdp_client"


def pyrefly_missing_attrs() -> dict[str, set[str]]:
    """mixin class name -> attribute names it is reported as lacking."""
    proc = subprocess.run(
        [sys.executable, "-m", "pyrefly", "check", "arena", "--output-format", "json"],
        cwd=ROOT, capture_output=True, text=True,
    )
    out: dict[str, set[str]] = defaultdict(set)
    try:
        errors = json.loads(proc.stdout or "{}").get("errors", [])
    except json.JSONDecodeError:
        return {}
    import re
    for err in errors:
        if err.get("name") != "missing-attribute":
            continue
        m = re.search(r"Object of class `(\w*Mixin)` has no attribute `(\w+)`",
                      err.get("description") or "")
        if m:
            out[m.group(1)].add(m.group(2))
    return dict(out)


def _module_files() -> list[Path]:
    return sorted((ROOT / PACKAGE).glob("*.py"))


def _class_defs() -> dict[str, tuple[Path, ast.ClassDef]]:
    found: dict[str, tuple[Path, ast.ClassDef]] = {}
    for path in _module_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                found[node.name] = (path, node)
    return found


def _concrete_users(mixin: str, classes: dict[str, tuple[Path, ast.ClassDef]]) -> list[str]:
    """Classes that inherit this mixin, directly OR transitively.

    The first version only looked at direct bases, which missed every mixin
    behind an intermediate: CDPTabManager inherits CDPTabManagerConnectMixin,
    which itself combines ConnectLaunch + ActiveConnect. Those two therefore
    appeared to have no concrete user at all, and ~90 findings were reported as
    "no owner declares it" when the owner was one level further up.
    """
    users: list[str] = []
    for name, (_, node) in classes.items():
        if name == mixin:
            continue
        if mixin in _mro_like(name, classes)[1:]:
            users.append(name)
    # Prefer the most derived class: it is the one that actually owns __init__.
    users.sort(key=lambda n: -len(_mro_like(n, classes)))
    return users


def _mro_like(cls: str, classes: dict[str, tuple[Path, ast.ClassDef]]) -> list[str]:
    """The class plus every base, breadth-first (good enough for these mixins)."""
    order, queue = [], [cls]
    while queue:
        cur = queue.pop(0)
        if cur in order or cur not in classes:
            continue
        order.append(cur)
        _, node = classes[cur]
        queue += [b.id for b in node.bases if isinstance(b, ast.Name)]
    return order


def _find_attr(attr: str, owners: list[str],
               classes: dict[str, tuple[Path, ast.ClassDef]]) -> str | None:
    """Render `attr` as a stub line, resolved from whichever owner defines it."""
    for owner in owners:
        if owner not in classes:
            continue
        _, node = classes[owner]

        # A method: copy the real signature text from the source, rather
        # than re-unparsing a synthesised node (which loses positions and
        # cannot be unparsed at all on 3.13).
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == attr:
                owner_path, _ = classes[owner]
                src_lines = owner_path.read_text(encoding="utf-8").splitlines()
                # The header runs from `def`/`async def` to the line ending in ':'
                head: list[str] = []
                for raw in src_lines[item.lineno - 1: (item.end_lineno or item.lineno)]:
                    head.append(raw.strip())
                    if raw.rstrip().endswith(":"):
                        break
                sig = " ".join(head)
                if not sig.endswith(":"):
                    return None
                return f"{sig} ..."

        # A class-level annotation.
        for item in node.body:
            if (isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
                    and item.target.id == attr):
                return f"{attr}: {ast.unparse(item.annotation)}"

        # An annotated assignment inside __init__.
        for item in node.body:
            if not (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == "__init__"):
                continue
            for sub in ast.walk(item):
                if (isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Attribute)
                        and sub.target.attr == attr):
                    return f"{attr}: {ast.unparse(sub.annotation)}"

        # A plain `self.x = <expr>` in __init__. Only two shapes are trusted,
        # both unambiguous; anything else falls through to "not guessing":
        #   * `self.x = param` where the parameter carries an annotation;
        #   * `self.x = <literal>` for bool/int/str/None.
        for item in node.body:
            if not (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == "__init__"):
                continue
            params = {a.arg: a.annotation for a in
                      [*item.args.posonlyargs, *item.args.args, *item.args.kwonlyargs]
                      if a.annotation is not None}
            for sub in ast.walk(item):
                if not (isinstance(sub, ast.Assign) and len(sub.targets) == 1):
                    continue
                tgt = sub.targets[0]
                if not (isinstance(tgt, ast.Attribute) and tgt.attr == attr
                        and isinstance(tgt.value, ast.Name) and tgt.value.id == "self"):
                    continue
                val = sub.value
                if isinstance(val, ast.Name) and val.id in params:
                    return f"{attr}: {ast.unparse(params[val.id])}"
                if isinstance(val, ast.Constant):
                    kind = type(val.value).__name__
                    if val.value is None:
                        continue  # bare None says nothing about the real type
                    if kind in ("bool", "int", "str", "float"):
                        return f"{attr}: {kind}"
    return None


def plan() -> tuple[dict[str, list[str]], list[str]]:
    classes = _class_defs()
    needed = pyrefly_missing_attrs()
    decls: dict[str, list[str]] = {}
    notes: list[str] = []

    for mixin, attrs in sorted(needed.items()):
        if mixin not in classes:
            notes.append(f"{mixin}: skipped (class not found in {PACKAGE})")
            continue
        users = _concrete_users(mixin, classes)
        if not users:
            notes.append(f"{mixin}: skipped (no concrete class inherits it)")
            continue
        # Search the concrete class and all of its bases (i.e. sibling mixins).
        owners: list[str] = []
        for user in users:
            for name in _mro_like(user, classes):
                if name != mixin and name not in owners:
                    owners.append(name)

        lines: list[str] = []
        for attr in sorted(attrs):
            rendered = _find_attr(attr, owners, classes)
            if rendered is None:
                notes.append(f"{mixin}.{attr}: skipped (no owner declares it; not guessing)")
                continue
            lines.append(rendered)
        if lines:
            decls[mixin] = lines
    return decls, notes


BANNER = (
    '    if TYPE_CHECKING:  # pragma: no cover - typing only\n'
    '        # Supplied by the concrete class that mixes this in. Declared, not\n'
    '        # assigned: annotations only, so runtime behaviour is unchanged.\n'
    '        # Written down because an undeclared interface lets a real typo\n'
    '        # hide among the noise it generates.\n'
)


def apply_decls(decls: dict[str, list[str]]) -> tuple[int, list[str]]:
    classes = _class_defs()
    notes: list[str] = []
    touched = 0

    by_file: dict[Path, list[tuple[str, list[str]]]] = defaultdict(list)
    for mixin, lines in decls.items():
        path, _ = classes[mixin]
        by_file[path].append((mixin, lines))

    for path, items in by_file.items():
        src = path.read_text(encoding="utf-8")
        before = ast.dump(ast.parse(src), include_attributes=False)
        lines = src.splitlines(keepends=True)

        # Bottom-up so earlier line numbers stay valid.
        for mixin, decl_lines in sorted(items, key=lambda kv: -classes[kv[0]][1].lineno):
            _, node = classes[mixin]
            if "if TYPE_CHECKING:" in "".join(lines[node.lineno - 1:node.body[0].lineno + 4]):
                notes.append(f"{mixin}: already declared, skipped")
                continue
            first = node.body[0]
            insert_at = first.end_lineno if isinstance(first, ast.Expr) and isinstance(
                getattr(first, "value", None), ast.Constant) else first.lineno - 1
            block = BANNER + "".join(f"        {ln}\n" for ln in decl_lines) + "\n"
            lines[insert_at:insert_at] = [block]
            touched += 1

        new_src = "".join(lines)
        if "from typing import TYPE_CHECKING" not in new_src:
            new_src = new_src.replace(
                "from __future__ import annotations\n",
                "from __future__ import annotations\n\nfrom typing import TYPE_CHECKING\n", 1)
        try:
            after_tree = ast.parse(new_src)
        except SyntaxError as exc:
            notes.append(f"{path}: REJECTED, does not parse: {exc}")
            continue

        # Only TYPE_CHECKING blocks and the import may have appeared.
        class Strip(ast.NodeTransformer):
            def visit_If(self, node):  # noqa: N802
                test = node.test
                if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                    return None
                self.generic_visit(node)
                return node

            def visit_ImportFrom(self, node):  # noqa: N802
                if node.module == "typing":
                    return None
                return node

        a = ast.dump(Strip().visit(ast.parse(src)), include_attributes=False)
        b = ast.dump(Strip().visit(after_tree), include_attributes=False)
        if a != b:
            notes.append(f"{path}: REJECTED, AST changed beyond the declarations")
            continue
        del before
        path.write_text(new_src, encoding="utf-8")
    return touched, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    decls, notes = plan()
    total = sum(len(v) for v in decls.values())
    print(f"mixins with an undeclared interface: {len(decls)}")
    print(f"  attributes to declare: {total}")
    for mixin, lines in sorted(decls.items()):
        print(f"   {mixin}: {len(lines)}")

    if args.apply and not args.check:
        touched, apply_notes = apply_decls(decls)
        notes.extend(apply_notes)
        print(f"  classes rewritten: {touched}")

    for n in notes[:30]:
        print("   ", n)
    if len(notes) > 30:
        print(f"    ... and {len(notes) - 30} more")
    return 1 if any("REJECTED" in n for n in notes) else 0


if __name__ == "__main__":
    raise SystemExit(main())

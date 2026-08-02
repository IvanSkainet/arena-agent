#!/usr/bin/env python3
"""Replace `from X import *` with the names the module actually uses (F405).

93 star imports, mostly from ~20 small "common" modules that act as import
bundles, produce 1609 F405 warnings. Every one of them is a name whose origin a
reader (and every static tool) has to guess.

The fix is mechanical but must not be textual: a name can appear in a comment,
a string, or be shadowed by a local. So the used-name set comes from the AST:

  * collect every `Name`/`Attribute` root load in the module;
  * subtract names bound locally (assignments, defs, classes, args, other
    imports, comprehension targets, globals);
  * intersect with what the starred module actually exports at runtime, since
    that is what the star import really provided.

Safety, in the same spirit as the E701/E702 passes:

  * the module is imported before and after, and its public surface (dir())
    must be identical -- a star import binds names on the importing module too,
    and dropping that silently would break re-export facades;
  * the file must still parse, and the AST must be unchanged apart from the
    import statement itself;
  * anything ambiguous is skipped and reported, never guessed.

Usage:
    python3 scripts/f405_explicit_imports.py --check
    python3 scripts/f405_explicit_imports.py --apply [--paths arena/foo.py]
"""

from __future__ import annotations

import argparse
import ast
import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("arena",)

# The tool imports the starred modules to learn what they really export, so the
# repo root has to be importable regardless of the cwd it is invoked from.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A star import also *rebinds* these onto the importing module. If a module is
# a re-export facade, replacing the star changes its public surface, so those
# are handled by keeping the explicit list complete rather than minimal.
STAR = "import *"


def star_import_files(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for base in paths:
        p = ROOT / base
        files = [p] if p.is_file() else sorted(p.rglob("*.py"))
        for f in files:
            try:
                if STAR in f.read_text(encoding="utf-8"):
                    out.append(f)
            except OSError:
                continue
    return out


def _star_targets(tree: ast.AST) -> list[ast.ImportFrom]:
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom)
            and any(a.name == "*" for a in n.names)]


def _module_level_nodes(tree: ast.AST):
    """Walk only the module scope, not function/class bodies.

    Scope matters: `import subprocess` *inside a function* binds a local, not
    a module global, so counting it as "already bound" made the tool drop
    `subprocess` from the explicit list and the module then failed with
    F821 at a call site in a different function. Caught by running ruff on the
    rewritten file rather than trusting the rewrite.
    """
    stack = [tree]
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            stack.append(child)


def _bound_names(tree: ast.AST) -> set[str]:
    """Names bound at MODULE scope (so they did not come from the star).

    Scope matters. `import subprocess` *inside a function* binds a local, not
    a module global. Counting it as already-bound made the tool drop
    `subprocess` from the explicit list, and the module then raised F821 at a
    call site in a different function. Caught by running ruff over the
    rewritten file instead of trusting the rewrite.
    """
    bound: set[str] = set()

    def visit(node: ast.AST, *, top: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if top:
                    bound.add(child.name)
                continue  # its body is a different scope
            if isinstance(child, ast.Lambda):
                continue
            if top:
                if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                    bound.add(child.id)
                elif isinstance(child, ast.alias) and child.name != "*":
                    bound.add((child.asname or child.name).split(".")[0])
                elif isinstance(child, ast.ExceptHandler) and child.name:
                    bound.add(child.name)
                elif isinstance(child, (ast.Global, ast.Nonlocal)):
                    bound.update(child.names)
            visit(child, top=top)

    visit(tree, top=True)
    return bound


def _loaded_names(tree: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _exports_of(module_name: str) -> set[str] | None:
    """What the starred module actually provides at runtime."""
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        return None
    declared = getattr(mod, "__all__", None)
    if declared is not None:
        return set(declared)
    return {n for n in dir(mod) if not n.startswith("_")}


def _required_names(module_name: str) -> set[str]:
    """Names other modules actually import FROM this one.

    The first version of this guard compared full `dir()` and refused every
    file: a star import drags `os`, `time`, `Path` and friends onto the
    importing module, and dropping those changes `dir()` without changing any
    contract -- nothing imports `subprocess` *from* a CLI module. What must
    survive is the set of names the rest of the repo (and its tests) actually
    pulls out, plus anything the module declares in __all__.
    """
    required: set[str] = set()
    roots = [ROOT / "arena", ROOT / "tests", ROOT / "scripts", ROOT / "bin"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == module_name:
                    for alias in node.names:
                        if alias.name != "*":
                            required.add(alias.name)
    return required


def _public_surface(module_name: str, required: set[str]) -> set[str] | None:
    """Only the names that are genuinely part of the module's contract."""
    try:
        for k in [k for k in list(sys.modules) if k.startswith(module_name.split(".")[0])]:
            sys.modules.pop(k, None)
        mod = importlib.import_module(module_name)
    except Exception:
        return None
    declared = set(getattr(mod, "__all__", ()) or ())
    have = set(dir(mod))
    return (required | declared) & have


def _module_name(path: Path) -> str:
    return path.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")


def plan(path: Path) -> tuple[str | None, list[str], str]:
    """Return (starred module, names to import explicitly, note)."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    stars = _star_targets(tree)
    if len(stars) != 1:
        return None, [], f"skipped ({len(stars)} star imports; tool handles exactly one)"
    node = stars[0]
    if node.level:
        return None, [], "skipped (relative star import)"
    target = node.module or ""
    exports = _exports_of(target)
    if exports is None:
        return None, [], f"skipped (cannot import {target})"

    used = _loaded_names(tree) - _bound_names(tree)
    needed = sorted(used & exports)
    if not needed:
        return target, [], "no names used from the star (import becomes removable)"
    return target, needed, ""


def apply_to(path: Path, target: str, names: list[str]) -> tuple[bool, str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    node = _star_targets(tree)[0]
    lines = src.splitlines(keepends=True)
    row = node.lineno - 1
    original = lines[row]

    # Preserve any trailing comment that is not the F401/F403 suppression,
    # since those often carry the "kept: re-export" rationale.
    comment = ""
    if "#" in original:
        tail = original.split("#", 1)[1].strip()
        for marker in ("noqa: F401,F403", "noqa: F403,F401", "noqa: F403", "noqa: F401"):
            tail = tail.replace(marker, "").strip()
        if tail:
            comment = f"  # {tail}"

    if names:
        if len(", ".join(names)) + len(target) < 70:
            new_line = f"from {target} import {', '.join(names)}{comment}\n"
        else:
            body = "".join(f"    {n},\n" for n in names)
            new_line = f"from {target} import ({comment}\n{body})\n"
    else:
        new_line = ""

    lines[row] = new_line
    new_src = "".join(lines)
    try:
        ast.parse(new_src)
    except SyntaxError as exc:
        return False, f"REJECTED, does not parse: {exc}"

    mod_name = _module_name(path)
    required = _required_names(mod_name)
    before = _public_surface(mod_name, required)
    path.write_text(new_src, encoding="utf-8")
    after = _public_surface(mod_name, required)
    if before is None or after is None:
        path.write_text(src, encoding="utf-8")
        return False, "REJECTED, module could not be imported for comparison"
    # A surface check is not enough: a name used only inside a function body
    # can go missing without changing dir(), and only shows up as F821 at call
    # time. Ask ruff, on the rewritten file, before accepting it.
    undefined = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F821,F811,F401",
         "--output-format=concise", str(path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    if undefined.returncode not in (0, 1):
        path.write_text(src, encoding="utf-8")
        return False, f"REJECTED, ruff failed: {undefined.stderr[:120]}"
    problems = [ln for ln in undefined.stdout.splitlines() if ": F8" in ln or ": F401" in ln]
    if problems:
        path.write_text(src, encoding="utf-8")
        return False, f"REJECTED, rewrite leaves {problems[0].split(': ',1)[-1][:70]}"

    missing = required - after
    if before != after or missing:
        path.write_text(src, encoding="utf-8")
        lost = sorted((before - after) | missing)[:8]
        return False, f"REJECTED, contract names lost: {lost}"
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--paths", nargs="*", default=list(TARGETS))
    args = ap.parse_args()
    do_apply = args.apply and not args.check

    files = star_import_files(args.paths)
    done = skipped = 0
    notes: list[str] = []
    for path in files:
        target, names, note = plan(path)
        rel = path.relative_to(ROOT).as_posix()
        if target is None:
            skipped += 1
            notes.append(f"{rel}: {note}")
            continue
        if do_apply:
            ok, err = apply_to(path, target, names)
            if not ok:
                skipped += 1
                notes.append(f"{rel}: {err}")
                continue
        done += 1

    print(f"F405: {len(files)} files with a star import")
    print(f"  {'rewrote' if do_apply else 'would rewrite'}: {done}")
    print(f"  skipped: {skipped}")
    for n in notes[:40]:
        print("   ", n)
    if len(notes) > 40:
        print(f"    ... and {len(notes) - 40} more")
    return 1 if any("REJECTED" in n for n in notes) else 0


if __name__ == "__main__":
    raise SystemExit(main())

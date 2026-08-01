#!/usr/bin/env python3
"""Re-export-aware F401 (unused import) cleanup.

Bulk `ruff --fix --select F401` is UNSAFE in this codebase: an import that
looks unused locally may be (a) re-exported — imported *from this module*
elsewhere, (b) a monkeypatch/mock target referenced by string name in
tests, or (c) a namespace-facade member (arena/runtime_deps — excluded
via ruff per-file-ignores). This script classifies every F401 finding:

    KEEP  -> annotate the import line with `# noqa: F401  # kept: ...`
             (the annotation doubles as documentation of WHY it stays)
    DROP  -> left flagged; `ruff check --fix --select F401` then removes
             exactly the un-annotated names.

Usage:
    python scripts/f401_reexport_clean.py --classify   # print summary only
    python scripts/f401_reexport_clean.py --apply      # annotate + fix
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NAME_RE = re.compile(r"^`(?P<name>[^`]+)` imported but unused$")
FROM_IMPORT_RE = re.compile(
    r"^\s*from\s+(?P<mod>[.\w]+)\s+import\s+(?P<tail>.+)$")
DYN_CTX_RE = re.compile(
    r"(setattr|getattr|delattr|monkeypatch|mock\.patch|patch\.dict|"
    r"__import__|importlib)")


def findings() -> list[dict]:
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "arena", "tests",
         "--select", "F401", "--output-format=json"],
        cwd=ROOT, capture_output=True, text=True)
    out = json.loads(proc.stdout or "[]")
    return [
        {"file": o["filename"], "row": o["location"]["row"],
         "name": m.group("name")}
        for o in out if (m := NAME_RE.match(o["message"]))
    ]


def module_refs(path: Path) -> set[str]:
    """All textual forms an importer might use for this module."""
    rel = path.relative_to(ROOT).with_suffix("")
    parts = rel.parts
    refs = {".".join(parts)}                     # arena.admin.auto_update
    refs.add(".".join(parts[:-1]))               # arena.admin (parent package)
    refs.add(parts[-1])                          # auto_update (same-dir import)
    return refs


def names_on_line(line: str, reported: str) -> set[str]:
    """Candidate binding/source names on the physical import line."""
    names = {reported}
    # ruff may report the fully-qualified path
    # ("arena.x.y.name imported but unused") — the binding is its tail
    if "." in reported:
        names.add(reported.rsplit(".", 1)[1])
    for a, b in re.findall(r"(\w+)\s+as\s+(\w+)", line):
        names.update((a, b))
    return names


def build_corpus() -> dict[Path, list[str]]:
    corpus = {}
    for p in list((ROOT / "arena").rglob("*.py")) + list(
            (ROOT / "tests").rglob("*.py")):
        corpus[p] = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return corpus


def classify_one(f: dict, corpus: dict[Path, list[str]]) -> str:
    path = Path(f["file"]).resolve()
    line = corpus[path][f["row"] - 1]
    names = names_on_line(line, f["name"])
    refs = module_refs(path)

    star_consumers = []  # modules doing `from <this module> import *`
    for other, lines in corpus.items():
        if other == path:
            continue
        # logical from-imports, incl. parenthesized multi-line forms:
        #   from a.b import (\n    name,\n)
        i = 0
        while i < len(lines):
            m = FROM_IMPORT_RE.match(lines[i])
            if m:
                tail = m.group("tail")
                j = i
                while "(" in tail and ")" not in tail and j + 1 < len(lines):
                    j += 1
                    tail += " " + lines[j].strip()
                mod = m.group("mod").lstrip(".")
                if mod in refs or any(mod == r.split(".")[-1] for r in refs):
                    if tail.strip().startswith("*"):
                        star_consumers.append(other)
                    for n in names:
                        if re.search(rf"\b{re.escape(n)}\b", tail):
                            return (f"re-export via from-import in "
                                    f"{other.relative_to(ROOT)}:{i + 1}")
                i = j
            i += 1
    # star-import consumption: `from <module> import *` in any consumer makes
    # every import in <module> potentially consumed (F405 channel)
    if star_consumers:
        names_list = ", ".join(o.relative_to(ROOT).as_posix()
                               for o in star_consumers[:3])
        return f"star-imported by {names_list}"
    # dynamic access by string name. Two justified shapes only (generic bare
    # names like "sys"/"platform" in an unrelated file are NOT evidence):
    #  a) dotted reference that ends with .name  -> patch("arena.x._helper")
    #  b) bare quoted name in a file that also from-imports the defining
    #     module -> monkeypatch.setattr(mod, "_helper", ...) with an
    #     `from arena.x import ...` in scope
    for other, lines in corpus.items():
        text_imports_module = False
        for ln in lines:
            im = FROM_IMPORT_RE.match(ln) or re.match(
                r"^\s*import\s+(?P<mod>[.\w]+)", ln)
            if im:
                mod = im.group("mod").lstrip(".")
                if mod in refs or any(mod == r.split(".")[-1] for r in refs):
                    text_imports_module = True
                    break
        for ln in lines:
            for n in names:
                # plain attribute consumption needs no dynamic context:
                # `mod.name` where mod traces back to the defining module
                if text_imports_module and re.search(
                        rf"\.{re.escape(n)}\b", ln):
                    return (f"attribute access with module in scope in "
                            f"{other.relative_to(ROOT)}")
            if not DYN_CTX_RE.search(ln):
                continue
            for n in names:
                # dotted patch target must name THIS module, not just any
                # attribute chain ending in the same word
                if re.search(
                        rf"['\"][\w.]*{re.escape(sorted(refs, key=len)[-1])}"
                        rf"\.{re.escape(n)}['\"]", ln):
                    return (f"dotted patch target on this module in "
                            f"{other.relative_to(ROOT)}")
                if text_imports_module and re.search(
                        rf"['\"]{re.escape(n)}['\"]", ln):
                    return (f"monkeypatch-by-name with module in scope in "
                            f"{other.relative_to(ROOT)}")
                # monkeypatch-by-name convention (AGENTS.md): tests patch
                # module attrs they never import; removing the binding
                # removes the attribute and breaks setattr at runtime
                if text_imports_module and re.search(
                        rf"(monkeypatch\.setattr|mock\.patch\.object|"
                        rf"patch\.object)\(\s*\w+\s*,\s*['\"]"
                        rf"{re.escape(n)}['\"]", ln):
                    return (f"module-attr patch target in "
                            f"{other.relative_to(ROOT)}")
    return ""


def main() -> int:
    fs = findings()
    corpus = build_corpus()
    keeps: dict[Path, dict[int, tuple[str, str]]] = defaultdict(dict)
    drops = 0
    for f in fs:
        why = classify_one(f, corpus)
        if why:
            keeps[Path(f["file"]).resolve()][f["row"]] = (f["name"], why)
        else:
            drops += 1

    total_keep = sum(len(v) for v in keeps.values())
    print(f"F401 findings: {len(fs)} | KEEP: {total_keep} | DROP: {drops}")
    for path, rows in sorted(keeps.items())[:400]:
        for row, (name, why) in sorted(rows.items()):
            print(f"  KEEP {path.relative_to(ROOT)}:{row} `{name}` ({why})")

    if "--apply" not in sys.argv[1:]:
        print("\n(classify only; rerun with --apply to annotate + ruff --fix)")
        return 0

    for path, rows in keeps.items():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for row, (name, why) in sorted(rows.items()):
            i = row - 1
            text = lines[i].rstrip("\n")
            if "noqa" in text:
                continue
            reason = "re-export/dynamic (AGENTS.md)"
            lines[i] = f"{text}  # noqa: F401  # kept: {reason}\n"
        path.write_text("".join(lines), encoding="utf-8")
        print(f"annotated {len(rows)} line(s) in {path.relative_to(ROOT)}")

    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "arena", "tests",
         "--select", "F401", "--fix"],
        cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout[-1200:] or proc.stderr[-1200:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

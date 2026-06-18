#!/usr/bin/env python3
"""Bump 3.2.2 -> 3.2.3."""
import pathlib
ROOT = pathlib.Path("/home/ivan/arena-bridge")

# constants.py
p = ROOT / "arena/constants.py"
t = p.read_text(encoding="utf-8")
p.write_text(t.replace('VERSION = "3.2.2"', 'VERSION = "3.2.3"', 1), encoding="utf-8")
print("OK: constants.py")

# pyproject.toml
p = ROOT / "pyproject.toml"
t = p.read_text(encoding="utf-8")
p.write_text(t.replace('version = "3.2.2"', 'version = "3.2.3"', 1), encoding="utf-8")
print("OK: pyproject.toml")

# CHANGELOG.md
p = ROOT / "CHANGELOG.md"
t = p.read_text(encoding="utf-8")
header = "# Changelog\n\n"
entry = """## v3.2.3 - 2026-06-19

### Added
- **MCP `fs.search` tool** — search file contents by regex pattern. Supports glob filter, context lines, case-insensitive mode, max_results limit. Skips sensitive files, hidden directories, and binary files.
- **MCP `fs.grep` tool** — alias for fs.search (familiar name for grep users).

### Security
- Path must be inside home directory (path traversal blocked)
- SENSITIVE_FILE_BASENAMES skipped (token.txt, .env, SSH keys, etc.)
- Hidden directories skipped (.git, __pycache__, node_modules, .venv)
- File size limit: 512KB per file; max 500 files scanned; max 200 results

### Tests
- tests/test_fs_search.py — 17 tests (basic search, directory search, no matches, errors, glob filter, ignore_case, context lines, max_results, blocked files, hidden dirs, grep alias, registry schema)

Total: **498 tests pass** (was 481, +17 new).

### Validation
- 498 tests pass (no regressions)
- py_compile OK
- Bridge /v1/doctor: 10/10

"""
t = header + entry + t[len(header):]
p.write_text(t, encoding="utf-8")
print("OK: CHANGELOG.md")
print("Done.")

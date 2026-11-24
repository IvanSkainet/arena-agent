"""The documented install, `pip install -e ".[full,dev]"`, provides what the tests import (#582)."""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import pytest

try:  # 3.11+ ships it; the 3.10 matrix cell installs tomli instead
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only on Python 3.10
    import tomli as tomllib

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
# Import name -> distribution name, where the two differ.
DISTRIBUTION = {"yaml": "pyyaml"}
# The documented command is run by pip, so pip is there without being listed.
INSTALLER = {"pip"}
# A handler for one of these catches a failed import. A bare `except:` does too.
CATCHES_A_FAILED_IMPORT = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
# Directories that hold no code of this project. A virtual environment is
# recognised by its pyvenv.cfg, whatever the directory is called.
FOREIGN = {"node_modules", "build", "dist", "site-packages"}


def declared() -> set[str]:
    """Return the distributions that the core, `full` and `dev` lists name."""
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    extras = project["optional-dependencies"]
    lines = project["dependencies"] + extras["full"] + extras["dev"]
    return {re.split(r"[<>=!~;\[ ]", line, maxsplit=1)[0].lower().replace("_", "-") for line in lines}


def project_files() -> list[Path]:
    """Return the Python files of this project, without virtual environments and installed packages."""
    files = []
    for folder, subfolders, names in os.walk(REPO):
        here = Path(folder)
        subfolders[:] = [
            name for name in subfolders
            if not name.startswith(".") and name not in FOREIGN and not (here / name / "pyvenv.cfg").exists()
        ]
        files += [here / name for name in names if name.endswith(".py")]
    return files


def own_names() -> set[str]:
    """Return every module and package name that lives in this repository."""
    names = set()
    for path in project_files():
        parts = path.relative_to(REPO).parts
        names.update(parts[:-1])
        names.add(path.stem)
    return names


def absolute_root(node: ast.ImportFrom) -> list[str]:
    """Return the package an absolute from-import loads; a relative one stays inside the project."""
    module = node.module if node.level == 0 else None
    return [module.split(".")[0]] if module else []


def roots(node: ast.stmt) -> list[str]:
    """Return the top-level package names that one import statement loads."""
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return absolute_root(node)
    return []


def tolerates_a_missing_package(node: ast.Try) -> bool:
    """Tell whether a failed import inside this try is caught by one of its handlers."""
    caught = set()
    for handler in node.handlers:
        if handler.type is None:
            return True
        caught.update(name.id for name in ast.walk(handler.type) if isinstance(name, ast.Name))
    return not caught.isdisjoint(CATCHES_A_FAILED_IMPORT)


# Functions and classes are not entered. The body of a `try` is left out only
# when one of its handlers catches a failed import: then the import in the
# body is optional, and the import in the handler is the fallback that must
# be there (`import tomllib` / `import tomli`). With `except ValueError` a
# missing package still stops collection, so that body is read.
def blocks(node: ast.stmt) -> list[list[ast.stmt]]:
    """Return the statement lists inside one statement that also run at import time."""
    if isinstance(node, ast.Try):
        body = [] if tolerates_a_missing_package(node) else [node.body]
        return body + [handler.body for handler in node.handlers] + [node.orelse, node.finalbody]
    if isinstance(node, (ast.If, ast.With, ast.For, ast.While)):
        return [node.body, getattr(node, "orelse", [])]
    return []


def module_scope(body: list[ast.stmt]) -> list[ast.stmt]:
    """Return every statement that runs at import time, through if, with, loops and try handlers."""
    found = []
    for node in body:
        found.append(node)
        for inner in blocks(node):
            found += module_scope(inner)
    return found


def third_party_imports() -> dict[str, str]:
    """Return each outside package a test file imports at module level, with one file that does."""
    known = set(sys.stdlib_module_names) | own_names() | INSTALLER
    found: dict[str, str] = {}
    for path in sorted(TESTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name in (name for node in module_scope(tree.body) for name in roots(node)):
            if name not in known:
                found.setdefault(name, path.name)
    return found


@pytest.fixture(name="needed")
def _needed() -> dict[str, str]:
    """Return the outside packages the test files import unconditionally."""
    return third_party_imports()


def test_the_scan_sees_the_imports_it_is_about(needed: dict[str, str]) -> None:
    """A scan that finds nothing would pass every check below."""
    assert {"pytest", "aiohttp", "yaml"} <= set(needed)
    # Found only through a try handler: the fallback import of this very file.
    assert "tomli" in needed
    assert "arena" not in needed
    assert "os" not in needed


def test_every_unconditional_import_of_a_test_file_is_installed_by_the_documented_command(
    needed: dict[str, str],
) -> None:
    """A module-level import of a package the install does not bring stops collection."""
    have = declared()
    missing = {
        name: path for name, path in needed.items()
        if DISTRIBUTION.get(name, name.lower().replace("_", "-")) not in have
    }
    assert not missing, f"add to the dev extra in pyproject.toml: {missing}"


def test_a_pytest_option_of_a_plugin_has_its_plugin_installed() -> None:
    """The `timeout` option and marker come from pytest-timeout; without it pytest refuses to start."""
    options = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]
    assert "timeout" in options
    assert "pytest-timeout" in declared()


def test_the_plugin_behind_the_parallel_option_is_installed() -> None:
    """Preflight and several tests start pytest with `-n`, which only pytest-xdist understands."""
    preflight = (REPO / "scripts" / "preflight.py").read_text(encoding="utf-8")
    assert '"-n"' in preflight
    assert "pytest-xdist" in declared()


def test_the_documents_name_the_command_this_test_guards() -> None:
    """If the documented command changes, this test must be pointed at the new one."""
    command = 'pip install -e ".[full,dev]"'
    assert command in (REPO / "README.md").read_text(encoding="utf-8")
    assert command in (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")

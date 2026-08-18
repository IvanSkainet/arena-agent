"""T65: required product imports may never disappear behind module skips."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import test_import_failopen_guard as guard


def test_guard_paths_are_bound_to_repository() -> None:
    root = Path(__file__).resolve().parents[1]
    assert guard.root_path() == root
    assert guard.tests_path() == root / "tests"


def _sample(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "test_sample.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_static_product_import_module_skip_is_rejected(tmp_path: Path) -> None:
    path = _sample(
        tmp_path,
        "import pytest\n"
        "try:\n"
        "    from arena.wiring.env import RuntimeEnv\n"
        "except Exception:\n"
        "    pytest.skip('hidden', allow_module_level=True)\n",
    )
    assert guard.scan_file(path) == [2]


def test_plain_product_import_module_skip_is_rejected(tmp_path: Path) -> None:
    path = _sample(
        tmp_path,
        "import pytest\n"
        "try:\n"
        "    import arena\n"
        "except Exception:\n"
        "    print('diagnostic')\n"
        "    pytest.skip('hidden', allow_module_level=True)\n",
    )
    assert guard.scan_file(path) == [2]


def test_dynamic_product_import_module_skip_is_rejected(tmp_path: Path) -> None:
    path = _sample(
        tmp_path,
        "import importlib\nimport pytest\n"
        "def load():\n"
        "    try:\n"
        "        return importlib.import_module('unified_bridge')\n"
        "    except Exception:\n"
        "        pytest.skip('hidden', allow_module_level=True)\n",
    )
    assert guard.scan_file(path) == [4]


@pytest.mark.parametrize(
    "source",
    [
        (
            "import importlib as il\nimport pytest as pt\n"
            "try:\n"
            "    il.import_module(name='arena.runtime')\n"
            "except Exception:\n"
            "    pt.skip('hidden', allow_module_level=True)\n"
        ),
        (
            "from importlib import import_module as load\n"
            "from pytest import skip as module_skip\n"
            "try:\n"
            "    load('unified_bridge')\n"
            "except Exception:\n"
            "    module_skip('hidden', allow_module_level=True)\n"
        ),
        (
            "import pytest\n\n"
            "try:\n"
            "    __import__('arena.runtime')\n"
            "except Exception:\n"
            "    pytest.skip('hidden', allow_module_level=True)\n"
        ),
    ],
)
def test_aliased_and_builtin_dynamic_forms_are_rejected(
    tmp_path: Path, source: str
) -> None:
    path = _sample(tmp_path, source)
    assert guard.scan_file(path) == [3]


def test_optional_dependency_and_non_skip_handlers_are_allowed(tmp_path: Path) -> None:
    optional = _sample(
        tmp_path,
        "import pytest\n"
        "try:\n"
        "    import hypothesis\n"
        "except ImportError:\n"
        "    pytest.skip('optional', allow_module_level=True)\n",
    )
    assert guard.scan_file(optional) == []
    similarly_named = _sample(
        tmp_path,
        "import pytest\n"
        "try:\n"
        "    import arena_tools\n"
        "except ImportError:\n"
        "    pytest.skip('optional', allow_module_level=True)\n",
    )
    assert guard.scan_file(similarly_named) == []
    required_without_skip = _sample(
        tmp_path,
        "try:\n"
        "    import arena\n"
        "except Exception as exc:\n"
        "    raise RuntimeError('broken') from exc\n",
    )
    assert guard.scan_file(required_without_skip) == []
    function_level_skip = _sample(
        tmp_path,
        "import pytest\n"
        "try:\n"
        "    import arena\n"
        "except Exception:\n"
        "    pytest.skip('local only', allow_module_level=False)\n",
    )
    assert guard.scan_file(function_level_skip) == []


def test_collect_reports_exact_repository_relative_findings(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "repo"
    tests = root / "tests"
    tests.mkdir(parents=True)
    hidden = tests / "test_hidden.py"
    hidden.write_text(
        "import pytest\n"
        "try:\n"
        "    import arena\n"
        "except Exception:\n"
        "    pytest.skip('hidden', allow_module_level=True)\n",
        encoding="utf-8",
    )
    source = hidden.read_text(encoding="utf-8")
    (tests / "helper.py").write_text(source, encoding="utf-8")
    (tests / "conftest.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(guard, "root_path", lambda: root)
    monkeypatch.setattr(guard, "tests_path", lambda: tests)
    assert guard.collect() == [
        "tests/conftest.py:2",
        "tests/test_hidden.py:2",
    ]


def test_main_reports_failure_and_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(guard, "collect", lambda: ["tests/test_hidden.py:2"])
    assert guard.main() == 1
    assert capsys.readouterr().out == (
        "required product imports fail open as module skips:\n"
        "  tests/test_hidden.py:2\n"
    )
    monkeypatch.setattr(guard, "collect", lambda: [])
    assert guard.main() == 0
    assert capsys.readouterr().out == (
        "OK: required product import failures remain collection errors\n"
    )


def test_current_tree_has_no_product_import_fail_open() -> None:
    assert guard.collect() == []

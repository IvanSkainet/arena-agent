"""Self-tests for ``dev/bump_version.py``.

The release-bump helper writes three files that must stay in sync. Since
it is now the one-command entry point for cutting a release, a regression
here would break every subsequent release. Test the actual script by
running it against a temporary copy of the three files.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUMP_SCRIPT = REPO_ROOT / "dev" / "bump_version.py"


def _load_bump_module():
    """Import ``dev/bump_version.py`` as a module without side-effects."""
    spec = importlib.util.spec_from_file_location("_bump_test_mod", BUMP_SCRIPT)
    assert spec and spec.loader, f"could not load {BUMP_SCRIPT}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def repo_copy(tmp_path, monkeypatch):
    """Copy release-bump-touched files into a tmp repo layout and
    monkey-patch the bump module's path constants to point at them."""
    dst = tmp_path / "repo"
    (dst / "arena").mkdir(parents=True)
    (dst / "tests").mkdir(parents=True)
    (dst / "chat_extension").mkdir(parents=True)
    (dst / "arena" / "constants.py").write_text(
        (REPO_ROOT / "arena" / "constants.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (dst / "pyproject.toml").write_text(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (dst / "tests" / "_version_matrix.py").write_text(
        (REPO_ROOT / "tests" / "_version_matrix.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for name in ("manifest.json", "content.js", "insert_strategies.js"):
        (dst / "chat_extension" / name).write_text(
            (REPO_ROOT / "chat_extension" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    mod = _load_bump_module()
    monkeypatch.setattr(mod, "REPO_ROOT", dst)
    monkeypatch.setattr(mod, "CONSTANTS_PY", dst / "arena" / "constants.py")
    monkeypatch.setattr(mod, "PYPROJECT_TOML", dst / "pyproject.toml")
    monkeypatch.setattr(mod, "VERSION_MATRIX_PY", dst / "tests" / "_version_matrix.py")
    monkeypatch.setattr(mod, "CHAT_EXT_DIR", dst / "chat_extension")
    monkeypatch.setattr(mod, "EXT_MANIFEST_JSON", dst / "chat_extension" / "manifest.json")
    monkeypatch.setattr(mod, "EXT_CONTENT_JS", dst / "chat_extension" / "content.js")
    monkeypatch.setattr(mod, "EXT_INSERT_JS", dst / "chat_extension" / "insert_strategies.js")
    return dst, mod


def test_bump_rejects_invalid_version_string(repo_copy):
    _dst, mod = repo_copy
    with pytest.raises(SystemExit):
        mod.main(["not-a-version"])


def test_dry_run_does_not_write(repo_copy):
    dst, mod = repo_copy
    before_c = (dst / "arena" / "constants.py").read_text(encoding="utf-8")
    before_p = (dst / "pyproject.toml").read_text(encoding="utf-8")
    before_m = (dst / "tests" / "_version_matrix.py").read_text(encoding="utf-8")
    rc = mod.main(["--dry-run", "99.99.99"])
    assert rc == 0
    assert (dst / "arena" / "constants.py").read_text(encoding="utf-8") == before_c
    assert (dst / "pyproject.toml").read_text(encoding="utf-8") == before_p
    assert (dst / "tests" / "_version_matrix.py").read_text(encoding="utf-8") == before_m


def test_full_bump_updates_all_three_files(repo_copy):
    dst, mod = repo_copy
    rc = mod.main(["99.99.99"])
    assert rc == 0
    assert 'VERSION = "99.99.99"' in (dst / "arena" / "constants.py").read_text(encoding="utf-8")
    py = (dst / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "99\.99\.99"\s*$', py, re.MULTILINE)
    vm = (dst / "tests" / "_version_matrix.py").read_text(encoding="utf-8")
    assert '"99.99.99"' in vm


def test_bumped_matrix_still_parses_and_has_new_last_entry(repo_copy):
    """After bump, ``_version_matrix.BRIDGE_VERSIONS[-1]`` must be the new version."""
    dst, mod = repo_copy
    mod.main(["99.99.99"])
    # Load the freshly-written matrix as a fresh module
    spec = importlib.util.spec_from_file_location(
        "_vm_test", dst / "tests" / "_version_matrix.py"
    )
    assert spec and spec.loader
    vm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vm)
    assert vm.BRIDGE_VERSIONS[-1] == "99.99.99"
    assert vm.LATEST_BRIDGE == "99.99.99"


def test_bump_refuses_same_version_twice(repo_copy):
    dst, mod = repo_copy
    mod.main(["99.99.99"])
    with pytest.raises(SystemExit):
        mod.main(["99.99.99"])


def test_script_is_executable_via_subprocess(tmp_path):
    """Sanity: the script's --help returns 0."""
    result = subprocess.run(
        [sys.executable, str(BUMP_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "bump" in result.stdout.lower() or "version" in result.stdout.lower()


# ---------------------------------------------------------------------------
# --extension path
# ---------------------------------------------------------------------------

def test_extension_bump_updates_manifest_content_and_matrix(repo_copy):
    import json
    dst, mod = repo_copy
    rc = mod.main(["--extension", "0.99.99"])
    assert rc == 0
    manifest = json.loads((dst / "chat_extension" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.99.99"
    content = (dst / "chat_extension" / "content.js").read_text(encoding="utf-8")
    assert "const ARENA_CONTENT_SCRIPT_VERSION = '0.99.99';" in content
    insert = (dst / "chat_extension" / "insert_strategies.js").read_text(encoding="utf-8")
    assert "return '0.99.99';" in insert
    vm = (dst / "tests" / "_version_matrix.py").read_text(encoding="utf-8")
    assert '"0.99.99"' in vm


def test_extension_dry_run_does_not_write(repo_copy):
    dst, mod = repo_copy
    before_m = (dst / "chat_extension" / "manifest.json").read_text(encoding="utf-8")
    before_c = (dst / "chat_extension" / "content.js").read_text(encoding="utf-8")
    before_i = (dst / "chat_extension" / "insert_strategies.js").read_text(encoding="utf-8")
    before_vm = (dst / "tests" / "_version_matrix.py").read_text(encoding="utf-8")
    rc = mod.main(["--extension", "--dry-run", "0.99.99"])
    assert rc == 0
    assert (dst / "chat_extension" / "manifest.json").read_text(encoding="utf-8") == before_m
    assert (dst / "chat_extension" / "content.js").read_text(encoding="utf-8") == before_c
    assert (dst / "chat_extension" / "insert_strategies.js").read_text(encoding="utf-8") == before_i
    assert (dst / "tests" / "_version_matrix.py").read_text(encoding="utf-8") == before_vm


def test_extension_refuses_same_version_twice(repo_copy):
    dst, mod = repo_copy
    mod.main(["--extension", "0.99.99"])
    with pytest.raises(SystemExit):
        mod.main(["--extension", "0.99.99"])

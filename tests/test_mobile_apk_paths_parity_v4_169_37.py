"""v4.169.37 -- arena.mobile.apk_paths parity tests (mutation-driven).

Fast, isolated tests for APK path containment and validation:
* `_err` envelope shape;
* `_staging_root` delegation;
* `_ensure_root` directory creation, error handling (OSError/ValueError) and staging_root in envelope;
* `ensure_within_staging` inside, matching, escaping (symlink / outside path), and resolution failure;
* `resolve_apk_path` validation:
  - non-string and whitespace client_path ("apk_path is required");
  - staging_root default fallback vs explicit root;
  - root creation error propagation;
  - lexical home reference ('~', '~/', '~\\') vs filename ('~weird.apk');
  - RuntimeError in expanduser handling with exact error and hint;
  - containment checks (resolved != root_resolved and root_resolved not in parents);
  - strict=False non-existent path resolution;
  - exists() and is_file() OSError/ValueError trapping ("invalid apk_path: ...");
  - non-existent file error with exact hint;
  - non-regular file error (directory at resolved path);
  - successful resolution returning resolved Path object.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.mobile.apk_paths as apk_paths  # noqa: E402


# --------------------------------------------------------------------
# 1. _err, _staging_root, _ensure_root
# --------------------------------------------------------------------
def test_err_schema():
    res = apk_paths._err("path error", field="val")
    assert res == {"ok": False, "error": "path error", "field": "val"}
    assert res["ok"] is False


def test_staging_root_returns_path():
    root = apk_paths._staging_root()
    assert isinstance(root, Path)


def test_ensure_root_success(tmp_path):
    target = tmp_path / "deep" / "nested" / "staging"
    assert apk_paths._ensure_root(target) is None
    assert target.is_dir()


def test_ensure_root_failure(tmp_path, monkeypatch):
    target = tmp_path / "unwritable"

    def _fail_mkdir(*a, **k):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(Path, "mkdir", _fail_mkdir)
    res = apk_paths._ensure_root(target)
    assert res == {
        "ok": False,
        "error": "could not create the staging directory: read-only filesystem",
        "staging_root": str(target),
    }


# --------------------------------------------------------------------
# 2. ensure_within_staging
# --------------------------------------------------------------------
def test_ensure_within_staging_valid_child(tmp_path):
    root = tmp_path / "staging"
    root.mkdir()
    child = root / "sub" / "app.apk"
    assert apk_paths.ensure_within_staging(child, root) is None


def test_ensure_within_staging_same_path(tmp_path):
    root = tmp_path / "staging"
    root.mkdir()
    assert apk_paths.ensure_within_staging(root, root) is None


def test_ensure_within_staging_escaped_path(tmp_path):
    root = tmp_path / "staging"
    root.mkdir()
    outside = tmp_path / "outside.apk"
    res = apk_paths.ensure_within_staging(outside, root)
    assert res == {
        "ok": False,
        "error": "resolved destination escapes the staging directory",
        "hint": "A symlink inside the staging tree pointed outside it. Nothing was written.",
        "staging_root": str(root.resolve()),
    }


def test_ensure_within_staging_nonexistent_root_strict_false(tmp_path):
    # If root does not exist on disk, strict=False allows resolving
    root = tmp_path / "nonexistent_root"
    child = root / "sub" / "app.apk"
    assert apk_paths.ensure_within_staging(child, root) is None


def test_ensure_within_staging_resolution_exception(tmp_path, monkeypatch):
    root = tmp_path / "staging"
    root.mkdir()
    child = root / "app.apk"
    orig_resolve = Path.resolve

    def _fail_resolve(self, strict=False):
        if self == child:
            raise RuntimeError("symlink loop")
        return orig_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _fail_resolve)
    res = apk_paths.ensure_within_staging(child, root)
    assert res == {
        "ok": False,
        "error": "could not resolve destination: symlink loop",
    }


# --------------------------------------------------------------------
# 3. resolve_apk_path
# --------------------------------------------------------------------
@pytest.mark.parametrize("bad_input", [None, "", "   ", 123, [], {}])
def test_resolve_apk_path_bad_input(tmp_path, bad_input):
    res = apk_paths.resolve_apk_path(bad_input, tmp_path / "staging")
    assert res == {"ok": False, "error": "apk_path is required"}


def test_resolve_apk_path_root_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        apk_paths, "_ensure_root", lambda r: {"ok": False, "error": "root failed"}
    )
    res = apk_paths.resolve_apk_path("app.apk", tmp_path / "staging")
    assert res == {"ok": False, "error": "root failed"}


def test_resolve_apk_path_home_runtime_error(tmp_path, monkeypatch):
    def _fail_expand(self):
        raise RuntimeError("no home dir")

    monkeypatch.setattr(Path, "expanduser", _fail_expand)
    res = apk_paths.resolve_apk_path("~/app.apk", tmp_path / "staging")
    assert res == {
        "ok": False,
        "error": "could not determine the home directory for '~/app.apk'",
        "hint": "Pass a path relative to the staging directory.",
    }


def test_resolve_apk_path_home_relative_expansion(tmp_path, monkeypatch):
    root = tmp_path / "staging"
    root.mkdir()
    apk_file = root / "rel.apk"
    apk_file.write_bytes(b"PK\x03\x04rel")

    monkeypatch.setattr(Path, "expanduser", lambda self: Path("rel.apk"))

    res = apk_paths.resolve_apk_path("~/rel.apk", root)
    assert isinstance(res, Path)
    assert res == apk_file.resolve()


def test_is_home_ref_cases(tmp_path):
    root = tmp_path / "staging"
    root.mkdir()

    # 1. '~' exact
    res_tilde = apk_paths.resolve_apk_path("~", root)
    assert isinstance(res_tilde, dict)
    assert "must live under the staging directory" in res_tilde["error"]

    # 2. '~/' posix prefix
    res_posix = apk_paths.resolve_apk_path("~/app.apk", root)
    assert isinstance(res_posix, dict)
    assert "must live under the staging directory" in res_posix["error"]

    # 3. '~\\' windows prefix
    res_win = apk_paths.resolve_apk_path("~\\app.apk", root)
    assert isinstance(res_win, dict)
    assert (
        "could not determine the home directory" in res_win["error"]
        or "must live under the staging directory" in res_win["error"]
    )

    # 4. '~filename.apk' is a literal filename, not a home ref
    (root / "~filename.apk").write_bytes(b"PK\x03\x04tilde")
    res_file = apk_paths.resolve_apk_path("~filename.apk", root)
    assert isinstance(res_file, Path)
    assert res_file == (root / "~filename.apk").resolve()


def test_resolve_apk_path_escapes_staging(tmp_path):
    root = tmp_path / "staging"
    root.mkdir()
    res = apk_paths.resolve_apk_path("../../etc/passwd", root)
    assert res == {
        "ok": False,
        "error": "apk_path must live under the staging directory",
        "hint": (
            f"Uploaded APKs go under {root}. Arbitrary host paths are rejected "
            "on purpose so a hijacked token can't install anything on disk."
        ),
        "staging_root": str(root),
    }


def test_resolve_apk_path_resolution_exception(tmp_path, monkeypatch):
    root = tmp_path / "staging"
    root.mkdir()

    def _fail_resolve(self, strict=False):
        raise OSError("filesystem I/O error")

    monkeypatch.setattr(Path, "resolve", _fail_resolve)
    res = apk_paths.resolve_apk_path("app.apk", root)
    assert res == {
        "ok": False,
        "error": "could not resolve apk_path: filesystem I/O error",
    }


def test_resolve_apk_path_exists_exception(tmp_path, monkeypatch):
    root = tmp_path / "staging"
    root.mkdir()

    def _fail_exists(self):
        raise OSError("ENAMETOOLONG")

    monkeypatch.setattr(Path, "exists", _fail_exists)
    res = apk_paths.resolve_apk_path("long_name.apk", root)
    assert res == {
        "ok": False,
        "error": "invalid apk_path: ENAMETOOLONG",
    }


def test_resolve_apk_path_not_found(tmp_path):
    root = tmp_path / "staging"
    root.mkdir()
    res = apk_paths.resolve_apk_path("missing.apk", root)
    expected_path = (root / "missing.apk").resolve()
    assert res == {
        "ok": False,
        "error": f"apk not found: {expected_path}",
        "hint": "Upload the APK first (POST it to root); then call prepare with the returned path.",
    }


def test_resolve_apk_path_not_a_file(tmp_path):
    root = tmp_path / "staging"
    root.mkdir()
    dir_target = root / "directory_not_file.apk"
    dir_target.mkdir()
    res = apk_paths.resolve_apk_path("directory_not_file.apk", root)
    assert res == {
        "ok": False,
        "error": f"apk_path is not a regular file: {dir_target.resolve()}",
    }


def test_resolve_apk_path_happy_path(tmp_path):
    root = tmp_path / "staging"
    root.mkdir()
    apk_file = root / "valid_app.apk"
    apk_file.write_bytes(b"PK\x03\x04valid-apk")

    res = apk_paths.resolve_apk_path("valid_app.apk", root)
    assert isinstance(res, Path)
    assert res == apk_file.resolve()


def test_resolve_apk_path_default_staging_root(monkeypatch, tmp_path):
    root = tmp_path / "default_staging"
    root.mkdir()
    apk_file = root / "default.apk"
    apk_file.write_bytes(b"PK\x03\x04apk")

    monkeypatch.setattr(apk_paths, "_staging_root", lambda: root)

    res = apk_paths.resolve_apk_path("default.apk")
    assert isinstance(res, Path)
    assert res == apk_file.resolve()

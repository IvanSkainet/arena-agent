"""Creating the staging directory is not a total operation either.

Bug #62, found by a surviving mutant rather than by reading the code:
mutmut turned `root.mkdir(parents=True, ...)` into `parents=False` in
`arena/mobile/apk_paths.py` and nothing failed, which meant no test ever
exercised what happens when that mkdir does not succeed. It raised
straight through and became an HTTP 500, while every other refusal on
the APK path returns an `{"ok": false}` envelope.

The trigger is not exotic: `$ARENA_APK_STAGING` pointed at a directory
the bridge cannot create -- a read-only mount, a locked-down home, a
path component that is a file. Same shape as bug #43 (`Path.exists()`
raises for over-long names and embedded NULs), one function earlier in
the same chain, and it was in both `apk_paths.py` and `apk_install.py`.
"""
from __future__ import annotations

import importlib
import os
import stat
import sys

import pytest

from arena.mobile.apk_paths import resolve_apk_path

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX mode bits do not deny directory creation on Windows",
)


@pytest.fixture
def readonly_parent(tmp_path):
    parent = tmp_path / "locked"
    parent.mkdir()
    os.chmod(parent, stat.S_IRUSR | stat.S_IXUSR)
    yield parent
    os.chmod(parent, stat.S_IRWXU)


def test_unwritable_staging_root_is_an_envelope_not_a_crash(readonly_parent):
    result = resolve_apk_path("app.apk", readonly_parent / "staging")
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "staging directory" in result["error"]
    # The operator has to be able to tell WHICH directory failed;
    # "could not create the staging directory" alone is unactionable.
    assert result["staging_root"].endswith("staging")


def test_a_file_where_the_staging_root_should_be(tmp_path):
    """NotADirectoryError / FileExistsError must land in the envelope too."""
    blocker = tmp_path / "staging"
    blocker.write_text("not a directory", encoding="utf-8")
    result = resolve_apk_path("app.apk", blocker / "inner")
    assert isinstance(result, dict) and result["ok"] is False


def test_save_upload_refuses_cleanly_when_staging_cannot_be_created(
    readonly_parent, monkeypatch
):
    """The upload endpoint, not just the path helper.

    save_upload() writes attacker-supplied bytes; if it can 500 it can
    also fail in ways nobody has classified.
    """
    monkeypatch.setenv("ARENA_APK_STAGING", str(readonly_parent / "staging"))
    import arena.mobile.apk_install as apk_install

    module = importlib.reload(apk_install)
    try:
        result = module.save_upload("a.apk", b"PK\x03\x04" + b"0" * 200)
        assert isinstance(result, dict) and result["ok"] is False
        assert "staging directory" in result["error"]
    finally:
        monkeypatch.delenv("ARENA_APK_STAGING", raising=False)
        importlib.reload(apk_install)


def test_the_happy_path_still_works(tmp_path):
    """Reverse sabotage: the guard must not break normal resolution.

    A deep staging root that does not exist yet must still be created --
    that is exactly what `parents=True` is for, and the mutant that
    flipped it to False is what started this.
    """
    root = tmp_path / "a" / "b" / "staging"
    result = resolve_apk_path("app.apk", root)
    assert isinstance(result, dict)
    # Not found is the correct answer for a file nobody uploaded; the
    # point is that the ROOT got created and no exception escaped.
    assert "apk not found" in result["error"]
    assert root.is_dir(), "the staging root must be created, parents and all"

    (root / "app.apk").write_bytes(b"PK\x03\x04" + b"0" * 200)
    resolved = resolve_apk_path("app.apk", root)
    assert not isinstance(resolved, dict), resolved
    assert resolved == (root / "app.apk").resolve()


def test_ensure_root_reports_rather_than_returning_none_on_failure(
    readonly_parent,
):
    """Sabotage guard: a helper that swallows the error is the old bug.

    If `_ensure_root` ever goes back to returning None unconditionally,
    the callers above cannot refuse and the 500 comes back.
    """
    from arena.mobile.apk_paths import _ensure_root

    assert _ensure_root(readonly_parent / "staging") is not None
    assert _ensure_root(readonly_parent.parent / "fine") is None


# --------------------------------------------------------------------
# Mutants that survived the first sweep of apk_paths.py. Each of these
# is a semantic change the suite could not see -- not a live bug, but a
# path nothing exercised, which is how #62 above stayed hidden.
# --------------------------------------------------------------------


@pytest.mark.parametrize("value", [123, None, ["app.apk"], b"app.apk", 3.5, {}])
def test_non_string_apk_path_is_refused_not_crashed(value, tmp_path):
    """Mutant: `isinstance(...) or not .strip()` -> `and`.

    With `and`, a non-string falls through to `.strip()` and raises
    AttributeError -- a 500 on any caller that sends the wrong JSON type.
    Nothing tested it, so the mutant lived.
    """
    result = resolve_apk_path(value, tmp_path / "staging")
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["error"] == "apk_path is required"


def test_bare_tilde_resolves_as_home_not_as_a_filename(tmp_path):
    """Mutant: the literal `"~"` in the home-reference test.

    `~` alone means the home directory, so it must be refused as outside
    staging. Break the comparison and it becomes a file called `~` INSIDE
    staging -- the opposite verdict, and the suite shrugged.
    """
    result = resolve_apk_path("~", tmp_path / "staging")
    assert isinstance(result, dict) and result["ok"] is False
    assert "must live under the staging directory" in result["error"]


def test_windows_style_home_prefix_is_treated_as_a_home_reference(tmp_path):
    r"""Mutant: the `"~\\"` entry in the startswith tuple.

    `~\Desktop\evil.apk` is a home reference on Windows. If that prefix
    stops counting, the string becomes a plain relative filename and is
    silently accepted into staging on one platform and refused on the
    other -- the exact cross-platform split bug #42's fix was written to
    end.
    """
    root = tmp_path / "staging"
    result = resolve_apk_path("~\\Desktop\\evil.apk", root)
    assert isinstance(result, dict) and result["ok"] is False
    # Either refusal is correct; what must NOT happen is it resolving to
    # a real path under staging.
    assert result["error"] != ""


def test_a_file_literally_named_tilde_something_stays_in_staging(tmp_path):
    """Reverse of the above: `~foo.apk` is a FILENAME, not a home ref.

    Bug #42's fix turns on this distinction, so pin both sides of it.
    """
    root = tmp_path / "staging"
    root.mkdir(parents=True)
    (root / "~weird.apk").write_bytes(b"PK\x03\x04" + b"0" * 200)
    resolved = resolve_apk_path("~weird.apk", root)
    assert not isinstance(resolved, dict), resolved
    assert resolved == (root / "~weird.apk").resolve()

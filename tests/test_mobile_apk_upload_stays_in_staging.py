"""An upload must never write outside the staging root (bug #41).

`save_upload` validated the destination *after* writing it. The order was:

    dest = STAGING_ROOT / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return prepare(filename)          # <- containment check lives in here

`prepare` -> `_resolve_apk_path` does refuse paths outside the staging
root, so the caller received a correct-looking
`{"ok": false, "error": "apk_path must live under the staging directory"}`
-- one step too late. The bytes were already on disk.

An ABSOLUTE filename reached that code because the only guard was
`any(p in ("..", "") for p in Path(filename).parts)`, and
`Path("/tmp/x").parts == ("/", "tmp", "x")` contains neither. Worse,
`STAGING_ROOT / "/tmp/x"` evaluates to `/tmp/x`: pathlib discards the left
operand when the right one is absolute.

Reproduced over live HTTP against a running bridge:

    POST /v1/mobile/apk/upload?filename=/tmp/HTTP_PWNED.apk
    -> 200 {"ok": false, ...}, and /tmp/HTTP_PWNED.apk exists (504 bytes).

Existing files were overwritten and absent parent directories were
created along the way. The error text even promised the opposite:
"Arbitrary host paths are rejected on purpose so a hijacked token can't
install anything on disk."

Sabotage record (mandatory per AGENTS.md) -- each guard was reverted and
proven to fail:
  1. removing the `is_absolute()` check
     -> test_absolute_filename_writes_nothing fails (file appears).
  2. removing the resolved-destination check
     -> test_symlink_inside_staging_cannot_escape fails.
  3. moving both checks back below `dest.write_bytes`
     -> test_rejected_upload_leaves_no_trace fails.
"""
from __future__ import annotations

import sys

import pytest


@pytest.fixture()
def staging(tmp_path, monkeypatch):
    """Point the module's staging root at a throwaway directory."""
    from arena.mobile import apk_install

    root = tmp_path / "apk-staging"
    root.mkdir()
    monkeypatch.setattr(apk_install, "STAGING_ROOT", root)
    return root


def _apk(payload: bytes = b"A" * 500) -> bytes:
    """Minimal bytes that pass the magic + size checks."""
    return b"PK\x03\x04" + payload


# ---------------------------------------------------------------------------
# The escape itself.
# ---------------------------------------------------------------------------

def test_absolute_filename_writes_nothing(staging, tmp_path):
    from arena.mobile.apk_install import save_upload

    outside = tmp_path / "escaped.apk"
    result = save_upload(str(outside), _apk())

    assert result["ok"] is False
    assert not outside.exists(), (
        "save_upload wrote outside the staging root: pathlib discards the "
        "left operand of `/` when the right operand is absolute."
    )


def test_absolute_filename_does_not_overwrite_an_existing_file(staging, tmp_path):
    """The original report: a hijacked token could clobber any writable file."""
    from arena.mobile.apk_install import save_upload

    victim = tmp_path / "important.conf"
    victim.write_text("ORIGINAL")

    result = save_upload(str(victim), _apk(b"OVERWRITTEN" * 50))

    assert result["ok"] is False
    assert victim.read_text() == "ORIGINAL"


def test_absolute_filename_does_not_create_directories(staging, tmp_path):
    """`dest.parent.mkdir(parents=True)` ran before any containment check."""
    from arena.mobile.apk_install import save_upload

    deep = tmp_path / "made" / "up" / "deep"
    save_upload(str(deep / "x.apk"), _apk())

    assert not deep.exists()


def test_rejected_upload_leaves_no_trace(staging, tmp_path):
    """Nothing at all may hit the filesystem on the refusal path."""
    from arena.mobile.apk_install import save_upload

    before = {p for p in tmp_path.rglob("*")}
    save_upload(str(tmp_path / "nope" / "x.apk"), _apk())
    after = {p for p in tmp_path.rglob("*")}

    assert before == after, f"refusal created: {sorted(after - before)}"


@pytest.mark.parametrize("filename", [
    "../escape.apk",
    "../../escape.apk",
    "a/../../escape.apk",
    "sub/../../../escape.apk",
])
def test_traversal_filenames_are_refused(staging, filename):
    from arena.mobile.apk_install import save_upload

    result = save_upload(filename, _apk())
    assert result["ok"] is False


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX symlink semantics; the guard itself is "
                           "platform-independent (Path.resolve).")
def test_symlink_inside_staging_cannot_escape(staging, tmp_path):
    """A symlink planted in the staging tree must not become a way out.

    This is why containment is re-checked on the RESOLVED path and not
    just on the raw string.
    """
    from arena.mobile.apk_install import save_upload

    # The target must ALREADY EXIST. An earlier version of this test
    # pointed the symlink at a missing directory, and then `mkdir` failed
    # with EEXIST for incidental reasons -- so the test passed even with
    # the containment check deleted. It was checking the wrong thing.
    # With a real directory behind the link the write goes through, which
    # is exactly the escape being guarded against.
    target = tmp_path / "outside"
    target.mkdir()
    (staging / "evil").symlink_to(target)

    result = save_upload("evil/x.apk", _apk())

    assert result["ok"] is False
    assert not (target / "x.apk").exists(), (
        "the upload followed a symlink out of the staging root"
    )
    assert not any(target.iterdir())


# ---------------------------------------------------------------------------
# A guard that blocks real uploads would just get removed.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "app.apk",
    "vendor/app.apk",
    "a/b/c/nested.apk",
    "with space.apk",
    "unicode-имя.apk",
    "dots.in.name.apk",
    "~literal-tilde.apk",  # a literal `~` is a legal filename character
])
def test_legitimate_uploads_still_work(staging, filename):
    from arena.mobile.apk_install import save_upload

    result = save_upload(filename, _apk())

    assert result["ok"] is True, f"{filename!r} was rejected: {result.get('error')}"
    written = staging / filename
    assert written.is_file()
    assert written.read_bytes() == _apk()


def test_successful_upload_reports_sha_and_consent(staging):
    """The upload -> install chain depends on this envelope."""
    from arena.mobile.apk_install import save_upload

    result = save_upload("app.apk", _apk())

    assert result["ok"] is True
    assert result["action"] == "apk_upload"
    assert result["written_bytes"] == len(_apk())
    assert len(result["sha256"]) == 64
    assert result["required_consent"].startswith("yes-install-")


def test_magic_and_size_checks_still_run_first(staging):
    from arena.mobile.apk_install import save_upload

    assert save_upload("x.apk", b"not an apk")["ok"] is False
    assert save_upload("x.apk", b"\x00\x01\x02\x03" + b"A" * 500)["ok"] is False
    assert not list(staging.iterdir())


# ---------------------------------------------------------------------------
# Bug #42, found by the `~literal-tilde.apk` case above: `Path.expanduser()`
# raises RuntimeError for a leading `~unknownuser`, and nothing caught it.
# ---------------------------------------------------------------------------

def test_unknown_user_tilde_is_refused_not_crashed(staging):
    """`prepare("~nosuchuser/x.apk")` used to raise RuntimeError -> HTTP 500.

    Every other bad input on this path returns an {"ok": false} envelope;
    this one escaped as an exception, which is a fail-open shape for a
    handler that is supposed to fail closed.
    """
    from arena.mobile.apk_install import prepare

    result = prepare("~nosuchuser-zzz/x.apk")  # user cannot exist

    assert isinstance(result, dict)
    assert result["ok"] is False


def test_tilde_home_reference_cannot_escape_staging(staging, monkeypatch, tmp_path):
    """`~/x.apk` expands to a real home dir -- which is outside staging."""
    from arena.mobile.apk_install import prepare

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    result = prepare("~/escape.apk")

    assert result["ok"] is False
    assert "staging" in str(result.get("error", "")).lower()


def test_no_input_makes_prepare_raise(staging):
    """Ratchet: the envelope contract holds for the whole nasty-input set."""
    from arena.mobile.apk_install import prepare

    nasty = [
        "~nosuchuser-zzz/x.apk", "~", "~/", "~~", "", "   ",
        "../x.apk", "/etc/passwd", "\x00.apk", "a" * 5000,
        "con", "nul", ".", "..", "./", "//", "a\nb.apk",
    ]
    for candidate in nasty:
        try:
            result = prepare(candidate)
        except Exception as exc:  # pragma: no cover - this is the failure
            pytest.fail(f"prepare({candidate!r}) raised {type(exc).__name__}: {exc}")
        assert isinstance(result, dict) and result.get("ok") is False, candidate


def test_save_upload_never_raises_on_hostile_filenames(staging):
    """Bug #43 on the write path: ENAMETOOLONG / embedded NUL escaped as
    exceptions instead of the {"ok": false} envelope every other rejection
    returns."""
    from arena.mobile.apk_install import save_upload

    # Deeply nested but legal names are NOT in this list on purpose:
    # `a/a/.../x.apk` stays inside the staging root and must succeed. The
    # property under test is "returns an envelope", and separately that
    # the unwritable ones report ok=False.
    nasty = [
        "a" * 5000, "sub/" + "b" * 5000, "x\x00y.apk", "", "   ",
        "." * 300 + ".apk",
    ]
    for candidate in nasty:
        try:
            result = save_upload(candidate, _apk())
        except Exception as exc:  # pragma: no cover - this is the failure
            pytest.fail(f"save_upload({candidate[:24]!r}...) raised "
                        f"{type(exc).__name__}: {exc}")
        assert isinstance(result, dict) and result.get("ok") is False

    # A legal deep path must still work -- the guard is about containment
    # and totality, not about being restrictive for its own sake.
    deep = save_upload("a/" * 50 + "x.apk", _apk())
    assert deep["ok"] is True


def test_absolute_filename_says_why_not_just_that_it_failed(staging, tmp_path):
    """Two layers guard this, and they are not interchangeable.

    The resolved-destination check alone already blocks the escape -- I
    verified that by deleting the `is_absolute()` guard and watching every
    other test in this file stay green. What the early guard adds is a
    caller-actionable message: "filename must be relative to the staging
    directory" instead of "resolved destination escapes...", which reads
    like an internal symlink problem rather than a usage error.

    Keeping the layer without pinning its distinguishing behaviour would
    mean the sabotage step cannot tell the two apart, so pin it here.
    """
    from arena.mobile.apk_install import save_upload

    result = save_upload(str(tmp_path / "x.apk"), _apk())

    assert result["ok"] is False
    assert "relative" in result["error"], (
        "the early absolute-path guard should explain the usage error; "
        f"got {result['error']!r}"
    )
    assert result.get("staging_root")


def test_tilde_handling_is_identical_on_posix_and_windows(staging, monkeypatch):
    """The `~` rule must not depend on what `expanduser()` does locally.

    This failed on CI and only on CI. POSIX `expanduser()` raises
    RuntimeError for an unknown user, so `~literal-tilde.apk` fell through
    to "it's just a filename". Windows expands it to a path under
    C:\\Users instead -- so the identical upload was a staging file on one
    runner and a rejected escape on another.

    The classification is now purely lexical (`~` or `~/...` is a home
    reference, anything else is a filename), which is the only way to get
    one answer for input that arrives over the network. Both platforms'
    expanduser behaviours are simulated here so the property is checked on
    every runner rather than on whichever one happens to disagree.
    """
    import pathlib

    from arena.mobile import apk_paths

    real_expanduser = pathlib.Path.expanduser

    def windows_like(self):
        text = str(self)
        if text.startswith("~"):
            return pathlib.Path("/simulated/home") / text[1:].lstrip("/\\")
        return self

    def posix_like(self):
        return real_expanduser(self)

    verdicts = {}
    for label, impl in (("posix", posix_like), ("windows", windows_like)):
        monkeypatch.setattr(pathlib.Path, "expanduser", impl)
        verdicts[label] = {}
        for name in ("~literal-tilde.apk", "~nosuchuser-zzz/x.apk",
                     "~/escape.apk", "~"):
            result = apk_paths.resolve_apk_path(name, staging)
            # A Path result or a plain "not found" both mean the name was
            # accepted as staging-relative; only the containment refusal
            # means the name was treated as pointing outside.
            #
            # Match the exact message, not the substring "staging": the
            # "apk not found: <path>" text embeds the staging path itself,
            # so a loose check reports every missing file as an escape.
            escaped = (isinstance(result, dict)
                       and str(result.get("error", "")).startswith(
                           "apk_path must live under the staging directory"))
            verdicts[label][name] = escaped

    assert verdicts["posix"] == verdicts["windows"], (
        "the same filename is classified differently depending on the "
        f"platform's expanduser(): {verdicts}"
    )
    assert verdicts["posix"]["~literal-tilde.apk"] is False
    assert verdicts["posix"]["~/escape.apk"] is True

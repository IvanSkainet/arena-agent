"""v4.169.33: kill the surviving mutation class in arena/files/sandbox.py.

The 2026-08-10 mutmut run produced 216 mutants, 89 survivors. Read one by
one they fall into four classes, and each class names the test that was
never written:

1. **Blocklist-entry removal** (~45 mutants). mutmut rewrites one literal
   of a refusal set (``"id_rsa"`` -> ``"XXid_rsaXX"``) and the set loses
   one protection. Every existing test exercised *some* entry, none
   exercised *all* of them -- so ``XXautonomyXX`` survived, meaning
   nothing proved the agent cannot read/edit the operator posture dir.

   The trap when fixing this: parametrizing the test over the LIVE module
   constant is tautological (a mutant that removes an entry also removes
   it from what the test iterates, and the mutant survives again). These
   tests therefore keep their own committed copy of each set and assert
   (a) set equality with the module and (b) runtime refusal of every
   entry in the *test-side* copy.

2. **Status-code drift** (400->401, 403->404, 404->405, 409->410,
   200->201). The statuses are the protocol: the "sensitivity before
   existence" ordering only keeps the 403-vs-404 oracle honest if the
   codes arrive unchanged. Pinned exactly.

3. **Sentinel message drift**. Short strings here function as enum
   tokens -- ``validate_upload_target`` literally compares
   ``err == "path outside home directory"`` to decide whether to reword.
   So the spelling is load-bearing and now pinned. Messages that name
   which rule fired are operator diagnostics (the module docstring says
   so) and are pinned too, along with the {action} verb threading.

4. **Equivalent sliding-window mutants** (4): the old
   ``range(len(parts) - len(want) + 1)`` arithmetic grew ``+`` mutants
   that cannot change behaviour (an over-long slice never equals the
   target tuple) while the shrinking ``-`` variants were already killed.
   The loops are rewritten in constant-free form via
   ``_contains_part_seq``; what remains *must* be killed: a mutant that
   mangles the window breaks the depth-placement tests below.

Expected outcome: ``python scripts/mutation_gate.py --list`` reports
survivors only where a mutant is provably equivalent; the baseline may
ratchet down, never up.
"""
from __future__ import annotations

import pytest

from arena.files import sandbox as sb

# --- committed copies of the module's refusal sets -------------------------
# If you add a protection to sandbox.py, extend the matching set here in
# the same commit; the equality tests below are intentionally noisy about
# drift in either direction.

EXPECTED_SENSITIVE_BASENAMES = frozenset({
    "token.txt", "users.json",
    ".env",
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "id_rsa.pub", "id_ed25519.pub", "id_ecdsa.pub", "id_dsa.pub",
    ".netrc", ".ssh_config",
    ".git-credentials", ".pypirc", ".npmrc", ".docker", ".dockercfg",
    ".kube", ".gitconfig",
    ".bash_history", ".zsh_history", ".sh_history", ".ash_history",
    ".fish_history", ".python_history", ".psql_history", ".mysql_history",
    ".rediscli_history", ".sqlite_history", ".node_repl_history",
})

EXPECTED_SENSITIVE_DIR_PREFIXES = frozenset({
    ".ssh", ".aws", ".gnupg", ".docker", ".kube",
    ".config/gh", ".config/git", ".mozilla",
    ".config/google-chrome", ".config/chromium",
    "autonomy",
})

EXPECTED_EXEC_WRITE_BASENAMES = frozenset({
    ".bashrc", ".bash_profile", ".bash_login", ".bash_logout",
    ".profile", ".zshrc", ".zprofile", ".zshenv", ".zlogin", ".zlogout",
    ".kshrc", ".cshrc", ".tcshrc", ".login",
    ".inputrc", ".vimrc", ".ideavimrc", ".tmux.conf", ".screenrc",
    "Microsoft.PowerShell_profile.ps1", "profile.ps1",
})

EXPECTED_EXEC_WRITE_DIR_PREFIXES = frozenset({
    ".config/autostart", ".config/fish", ".config/systemd",
    ".local/bin", ".bashrc.d", ".profile.d", ".zshrc.d", "bin",
})


@pytest.fixture
def px(tmp_path):
    """A home with a workspace root inside it and an outside world."""
    home = tmp_path / "home"
    home.mkdir()
    root = home / "workspace"
    root.mkdir()
    bridge_dir = home / "bridge"
    bridge_dir.mkdir()
    bridge_py = bridge_dir / "unified_bridge.py"
    bridge_py.write_text("# fake bridge entry point\n")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    plain = home / "notes"
    plain.mkdir()
    (plain / "plain.txt").write_text("ordinary file\n")
    return {"home": home, "root": root, "bridge_py": bridge_py,
            "outside": outside, "plain": plain}


def _verb(fn, target, px, **kw):
    return fn(target, root=px["root"], home=px["home"], **kw)


VERBS_WRITE = ("uploading", "editing", "creating")
VERBS_READ = ("downloading", "viewing")


def _call(verb, px, target):
    kw = {}
    if verb in ("uploading", "editing", "creating"):
        kw["bridge_py"] = px["bridge_py"]
    fn = {
        "uploading": sb.validate_upload_target,
        "downloading": sb.validate_download_target,
        "editing": sb.validate_edit_target,
        "viewing": sb.validate_view_target,
        "creating": sb.validate_create_target,
    }[verb]
    return _verb(fn, target, px, **kw)


# --- 1. the module's sets are exactly the committed ones --------------------

def test_sensitive_basenames_match_committed_set():
    assert sb.SENSITIVE_FILE_BASENAMES == EXPECTED_SENSITIVE_BASENAMES


def test_sensitive_dir_prefixes_match_committed_set():
    assert sb.SENSITIVE_DIR_PREFIXES == EXPECTED_SENSITIVE_DIR_PREFIXES


def test_exec_write_basenames_match_committed_set():
    assert sb.EXECUTION_ON_WRITE_BASENAMES == EXPECTED_EXEC_WRITE_BASENAMES


def test_exec_write_dir_prefixes_match_committed_set():
    assert sb.EXECUTION_ON_WRITE_DIR_PREFIXES == EXPECTED_EXEC_WRITE_DIR_PREFIXES


def test_edit_blocked_basenames_alias_is_identical_object():
    # Backcompat promise from v3.2.0: the alias points at the SAME object,
    # not a copy and never None (a mutmut-variant set it to None and no
    # test noticed).
    assert sb._EDIT_BLOCKED_BASENAMES is sb.SENSITIVE_FILE_BASENAMES


# --- 2. every sensitive basename is refused by every verb -------------------

@pytest.mark.parametrize("name", sorted(EXPECTED_SENSITIVE_BASENAMES))
@pytest.mark.parametrize("verb", VERBS_WRITE + VERBS_READ)
def test_every_sensitive_basename_refused(px, name, verb):
    target = str(px["home"] / "sub" / name)
    path, err, status = _call(verb, px, target)
    assert path is None
    assert status == 403
    assert err == f"{verb} {name} is not allowed"


# --- 3. every sensitive dir prefix is refused by every verb -----------------

@pytest.mark.parametrize("prefix", sorted(EXPECTED_SENSITIVE_DIR_PREFIXES))
@pytest.mark.parametrize("verb", VERBS_WRITE + VERBS_READ)
def test_every_sensitive_dir_prefix_refused(px, prefix, verb):
    target = str(px["home"] / prefix / "probe")
    path, err, status = _call(verb, px, target)
    assert path is None
    assert status == 403
    assert err == f"{verb} files under {prefix}/ is not allowed"


@pytest.mark.parametrize("verb", VERBS_WRITE + VERBS_READ)
def test_sensitive_prefix_at_deep_position_still_refused(px, verb):
    # A sensitive dir NAME anywhere in the path is blocked, not only at
    # its "official" depth -- this is also the depth placement that kills
    # a shrunk sliding window.
    target = str(px["home"] / "work" / "project" / ".ssh" / "key")
    path, err, status = _call(verb, px, target)
    assert path is None
    assert status == 403
    assert err == f"{verb} files under .ssh/ is not allowed"


@pytest.mark.parametrize("verb", VERBS_WRITE + VERBS_READ)
def test_multi_segment_prefix_at_window_end_refused(px, verb):
    # `.config/gh` occupies the LAST window position here; an off-by-one
    # sliding window (len(parts) - n windows instead of +1) never sees it.
    target = str(px["home"] / "proj" / ".config" / "gh")
    path, err, status = _call(verb, px, target)
    assert path is None
    assert status == 403
    assert err == f"{verb} files under .config/gh/ is not allowed"


# --- 4. exec-on-write: writes refused, reads allowed ------------------------

@pytest.mark.parametrize("name", sorted(EXPECTED_EXEC_WRITE_BASENAMES))
@pytest.mark.parametrize("verb", VERBS_WRITE)
def test_every_exec_write_basename_refused_for_writes(px, name, verb):
    target = str(px["home"] / name)
    path, err, status = _call(verb, px, target)
    assert path is None
    assert status == 403
    assert err == (f"{verb} {name} is not allowed: it is executed "
                   "on shell startup, so writing it would be code execution")


@pytest.mark.parametrize("name", sorted(EXPECTED_EXEC_WRITE_BASENAMES))
@pytest.mark.parametrize("verb", VERBS_READ)
def test_exec_write_basenames_still_readable(px, name, verb):
    # Read access is deliberately untouched (reverse sabotage: an over-
    # broad block would break agents inspecting shell configuration).
    target = px["home"] / name
    target.write_text("# config\n")
    path, err, status = _call(verb, px, str(target))
    assert err is None
    assert status == 200
    assert path is not None


@pytest.mark.parametrize("prefix", sorted(EXPECTED_EXEC_WRITE_DIR_PREFIXES))
@pytest.mark.parametrize("verb", VERBS_WRITE)
def test_every_exec_write_dir_prefix_refused_for_writes(px, prefix, verb):
    target = str(px["home"] / prefix / "tool")
    path, err, status = _call(verb, px, target)
    assert path is None
    assert status == 403
    assert err == (f"{verb} files under {prefix}/ is not allowed: "
                   "they are executed or auto-started")


@pytest.mark.parametrize("prefix", sorted(EXPECTED_EXEC_WRITE_DIR_PREFIXES))
@pytest.mark.parametrize("verb", VERBS_READ)
def test_exec_write_dir_prefixes_still_readable(px, prefix, verb):
    d = px["home"] / prefix
    d.mkdir(parents=True)
    f = d / "tool"
    f.write_text("#!/bin/sh\n")
    path, err, status = _call(verb, px, str(f))
    assert err is None
    assert status == 200


@pytest.mark.parametrize("verb", VERBS_WRITE)
def test_exec_prefix_at_window_end_refused(px, verb):
    # prefix occupies the last possible window position.
    target = str(px["home"] / "proj" / ".local" / "bin" / "tool")
    path, err, status = _call(verb, px, target)
    assert path is None
    assert status == 403
    assert err == (f"{verb} files under .local/bin/ is not allowed: "
                   "they are executed or auto-started")


# --- 5. reverse sabotage: lookalikes must stay allowed ----------------------

def test_config_dir_not_in_the_list_stays_allowed(px):
    # Only gh/git/browsers under ~/.config are sensitive; other config
    # must not be collateral (this test is the reason the single-segment
    # match is by exact component, not by startswith).
    d = px["home"] / ".config" / "htop"
    d.mkdir(parents=True)
    f = d / "htoprc"
    f.write_text("# ok\n")
    for verb in VERBS_WRITE + VERBS_READ:
        target = str(f)
        if verb == "creating":
            target = str(d / "new.conf")  # create must target a fresh path
        path, err, status = _call(verb, px, target)
        assert err is None, f"{verb} wrongly refused a safe .config dir"
        assert status == 200


def test_dir_whose_name_startswith_a_prefix_stays_allowed(px):
    d = px["home"] / "binify"
    d.mkdir()
    f = d / "tool"
    f.write_text("x\n")
    for verb in VERBS_WRITE + VERBS_READ:
        target = str(f)
        if verb == "creating":
            target = str(d / "new-tool")
        path, err, status = _call(verb, px, target)
        assert err is None
        assert status == 200


# --- 6. sentinel statuses and messages --------------------------------------

@pytest.mark.parametrize("verb", VERBS_WRITE + VERBS_READ)
def test_missing_path(px, verb):
    path, err, status = _call(verb, px, "")
    assert (path, err, status) == (None, "missing path", 400)


@pytest.mark.parametrize("verb", VERBS_WRITE + VERBS_READ)
@pytest.mark.parametrize("target", ["a/../b", "../x"])
def test_traversal_refused_before_resolution(px, verb, target):
    # "a/../b" resolves INSIDE home -- only the literal ".." check refuses
    # it. A mutant nulling that check cannot hide behind the resolved-
    # path check for this input.
    path, err, status = _call(verb, px, target)
    assert (path, err, status) == (None, "path traversal not allowed", 400)


@pytest.mark.parametrize("verb", VERBS_READ + ("editing",))
def test_outside_home_passthrough_message(px, verb):
    target = str(px["outside"] / "x.txt")
    path, err, status = _call(verb, px, target)
    assert (path, err, status) == (None, "path outside home directory", 403)


@pytest.mark.parametrize("verb,expected", [
    ("uploading", "upload path must be inside user home"),
    ("creating", "create path must be inside user home"),
])
def test_outside_home_is_reworded_for_upload_and_create(px, verb, expected):
    # The rewording branch keys on the exact sentinel string from
    # resolve_home_path; mutants on either side of that compare change
    # the message seen here.
    target = str(px["outside"] / "x.txt")
    path, err, status = _call(verb, px, target)
    assert (path, err, status) == (None, expected, 403)


@pytest.mark.parametrize("verb", VERBS_READ + ("editing",))
def test_missing_file_is_404_with_protocol_message(px, verb):
    path, err, status = _call(verb, px, str(px["home"] / "notes" / "gone.txt"))
    assert (path, err, status) == (None, "file not found", 404)


@pytest.mark.parametrize("verb", VERBS_READ + ("editing",))
def test_directory_is_not_a_file(px, verb):
    # `not exists() or not is_file()` mutants (`or` -> `and`) let a
    # directory through to the handler, which later crashes opening it.
    d = px["home"] / "notes" / "subdir"
    d.mkdir()
    path, err, status = _call(verb, px, str(d))
    assert (path, err, status) == (None, "file not found", 404)


def test_create_on_existing_file_is_409_with_protocol_message(px):
    path, err, status = _call("creating", px, str(px["plain"] / "plain.txt"))
    assert path is None
    assert status == 409
    assert err == ("file already exists: plain.txt "
                   "(use PATCH /v1/fs/edit to modify)")


# --- 7. bridge self-protection, all three mutating verbs --------------------

@pytest.mark.parametrize("verb,expected", [
    ("uploading", "cannot overwrite the bridge itself"),
    ("editing", "cannot edit the bridge itself"),
    ("creating", "cannot overwrite the bridge itself"),
])
def test_bridge_self_protection_exact_contract(px, verb, expected):
    path, err, status = _call(verb, px, str(px["bridge_py"]))
    assert (path, err, status) == (None, expected, 403)


# --- 8. success tuple: path set, no error, status exactly 200 ---------------

@pytest.mark.parametrize("verb", VERBS_WRITE + VERBS_READ)
def test_success_status_is_200(px, verb):
    if verb == "creating":
        target = str(px["home"] / "notes" / "new.txt")
    else:
        target = str(px["plain"] / "plain.txt")
    path, err, status = _call(verb, px, target)
    assert err is None
    assert status == 200
    assert path is not None


def test_resolve_home_path_success_status_is_200(px):
    # The validators return their own 200 on success, so a 200->201
    # mutation inside resolve_home_path is only observable here.
    from arena.files.sandbox import resolve_home_path
    path, err, status = resolve_home_path(
        "workspace/anything.txt", root=px["root"], home=px["home"])
    assert err is None
    assert status == 200
    assert path is not None

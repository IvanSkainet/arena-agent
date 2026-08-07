"""User store tests."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import unified_bridge as ub  # noqa: E402
from arena.auth.users import UserStore  # noqa: E402


def test_user_store_load_add_remove(tmp_path):
    path = tmp_path / "users.json"
    store = UserStore(path)
    assert store.load_users() == {}
    store.add_or_update_user(name="alice", token="tok", role="user")
    users = store.load_users()
    assert users["tok"]["name"] == "alice"
    assert users["tok"]["role"] == "user"
    assert store.remove_user("alice") is True
    assert store.remove_user("alice") is False


def test_unified_bridge_user_wrappers():
    assert callable(ub._load_users)
    assert callable(ub.check_auth_with_role)


def test_a_torn_user_file_does_not_read_as_an_empty_roster(tmp_path):
    """Bug #74: an interrupted write used to delete every account.

    `write_users_data` was a bare `write_text`, which truncates first and
    writes second. A crash, a full disk, or a kill -9 in that window
    leaves a partial file. `read_users_data` then caught the parse error
    and returned `{"users": []}` -- indistinguishable from first run --
    and the next `add_or_update_user` rebuilt the file from that empty
    list, making a recoverable corruption permanent.

    Measured on the unfixed pair: 60 accounts seeded, the file truncated
    to 60%, and `load_users()` returned `{}` while the next write left a
    file with one entry. Sixty tokens gone, no error anywhere.

    A damaged roster must fail closed, because the alternative is
    silently deleting credentials.
    """
    from arena.auth.users import UsersFileCorrupt

    path = tmp_path / "users.json"
    store = UserStore(path)
    for index in range(20):
        store.add_or_update_user(name=f"user{index}",
                                 token=f"token{index:040d}", role="user")
    assert len(store.read_users_data()["users"]) == 20

    intact = path.read_bytes()
    path.write_bytes(intact[: int(len(intact) * 0.6)])
    torn = path.read_bytes()
    store.invalidate()

    with pytest.raises(UsersFileCorrupt):
        store.read_users_data()

    # The important half: the rewrite path must refuse too, and must not
    # have touched the bytes on the way to refusing.
    with pytest.raises(UsersFileCorrupt):
        store.add_or_update_user(name="intruder", token="x" * 40, role="admin")
    assert path.read_bytes() == torn, "the damaged file was overwritten"

    # Recovery has to actually work, otherwise failing closed is just a
    # different way of losing the accounts.
    path.write_bytes(intact)
    store.invalidate()
    assert len(store.read_users_data()["users"]) == 20


def test_authentication_still_degrades_instead_of_locking_everyone_out(tmp_path):
    """Reverse sabotage for #74.

    Failing closed on the *write* path must not become failing closed on
    the *auth* path. `load_users` runs on every authenticated request; if
    it started raising, a corrupt user file would take the whole bridge
    offline rather than falling back to the primary admin token. Losing
    multi-user accounts is bad, losing all access is worse.
    """
    path = tmp_path / "users.json"
    store = UserStore(path)
    store.add_or_update_user(name="alice", token="a" * 40, role="user")
    intact = path.read_bytes()
    path.write_bytes(intact[: int(len(intact) * 0.5)])
    store.invalidate()

    assert store.load_users() == {}  # no exception, no accounts honoured


def test_a_missing_user_file_is_first_run_not_corruption(tmp_path):
    """Reverse sabotage for #74: absence is not damage.

    The fix keys on "exists but unparseable". If it keyed on "did not
    parse" alone, every fresh install would raise on its first request.
    """
    store = UserStore(tmp_path / "never-created.json")
    assert store.read_users_data() == {"users": []}
    assert store.load_users() == {}
    store.add_or_update_user(name="first", token="f" * 40, role="admin")
    assert len(store.read_users_data()["users"]) == 1


def test_the_user_file_is_never_truncated_in_place(tmp_path, monkeypatch):
    """The other half of #74, checked by behaviour rather than by source.

    The first version of this test grepped `inspect.getsource` for
    `os.replace`. It passed against a sabotaged build that had the bare
    `write_text` restored -- because the docstring explaining the fix
    still contained the words `os.replace` and `fsync`. A test that
    reads its own prose is not a test. (Same rake as the scanner that
    flagged its own docstrings.)

    So: observe the syscalls instead. The destination must never be
    opened for writing, because that is what truncates it and creates
    the window where a crash destroys every account. Writes go to some
    other path, and the destination only ever appears as the target of
    an atomic replace.
    """
    import builtins

    path = tmp_path / "users.json"
    store = UserStore(path)
    store.add_or_update_user(name="seed", token="s" * 40, role="user")

    opened_for_write: list[str] = []
    real_open = builtins.open
    real_replace = os.replace
    replaced_onto: list[str] = []

    def watching_open(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in ("w", "a", "+", "x")):
            opened_for_write.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    def watching_replace(src, dst, *args, **kwargs):
        replaced_onto.append(str(dst))
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", watching_open)
    monkeypatch.setattr(os, "replace", watching_replace)
    try:
        store.add_or_update_user(name="second", token="x" * 40, role="user")
    finally:
        monkeypatch.undo()

    assert str(path) not in opened_for_write, (
        f"{path.name} was opened for writing directly -- that truncates it "
        f"and reopens the #74 window; writes must land on a temp file")
    assert str(path) in replaced_onto, "the destination was never atomically replaced"
    assert opened_for_write, "nothing was written at all -- test is not exercising the path"

    # The write still has to have worked, and leave no debris.
    assert len(store.read_users_data()["users"]) == 2
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "users.json"]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_a_failed_write_leaves_the_previous_roster_intact(tmp_path, monkeypatch):
    """#74, the case that actually loses data: the write dies mid-flight.

    With `write_text` the destination was already truncated by the time
    anything could fail, so a failure at this point *was* the data loss.
    With a temp file plus replace, a failure must leave the old roster
    byte-identical.
    """
    path = tmp_path / "users.json"
    store = UserStore(path)
    for index in range(10):
        store.add_or_update_user(name=f"u{index}", token=f"t{index:040d}",
                                 role="user")
    intact = path.read_bytes()

    def exploding_replace(src, dst, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", exploding_replace)
    with pytest.raises(OSError):
        store.add_or_update_user(name="doomed", token="d" * 40, role="user")
    monkeypatch.undo()

    assert path.read_bytes() == intact, "a failed write damaged the roster"
    store.invalidate()
    assert len(store.read_users_data()["users"]) == 10
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "users.json"]
    assert leftovers == [], f"temp file survived a failed write: {leftovers}"

"""A watch target the fs endpoints accept must not be a 500 here.

The fuzzing gate (#258) found this the honest way: `POST /v1/watch/files`
with `{"path": {}}` -- a dict where the schema says string -- came back

    500 {"error": "ValueError: '/tmp/fuzz-root-.../{}' is not in the subpath
         of '/home/user'"}

`resolve_home_path` (the shared jail) accepts the workspace root, the agent's
state directory and the caller's home; the watch runtime then re-checked the
same path with `relative_to(home)`, which knows only about home and raises
`ValueError` for everything else. One gate widening the jail and the other not
means a rule nobody can satisfy: the request is refused, so it cannot be
correct, and it is a crash, so it is not a refusal either.

The tests below pin the three cases that matter -- inside the workspace root
but outside home, outside all three, and the dict that found this -- to the
same answers the fs endpoints give.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from arena.files.sandbox import resolve_home_path
from arena.filewatch.runtime import FileWatchRuntimeContext, make_file_watch_runtime


def _runtime(*, home: Path, root: Path):
    return make_file_watch_runtime(
        FileWatchRuntimeContext(
            home=home,
            default_root=root,
            emit_event=lambda *a, **k: None,
            utc_now=lambda: "now",
            log_info=lambda *a, **k: None,
            log_warning=lambda *a, **k: None,
            poll_interval_s=0.01,
            max_files_per_watch=50,
        )
    )


def _add(runtime, path: str, root: Path):
    return runtime.add_sync(path=path, root=root, recursive=False, patterns=[], label="", created_at="now")


def test_a_watch_on_the_workspace_root_works_even_when_home_is_elsewhere(tmp_path):
    """`serve --root` outside `$HOME` is the arrangement the bridge documents.

    An agent pointed at a workspace it cannot watch is watching nothing: the
    fs endpoints already read that tree (#B-030), so the watcher has to.
    """
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    (home / "sub").mkdir(parents=True)
    (workspace / "sub").mkdir(parents=True)
    runtime = _runtime(home=home, root=workspace)

    added = _add(runtime, str(workspace / "sub"), workspace)

    assert added["ok"] is True, added
    assert added["path"] == str(workspace / "sub")


def test_a_watch_outside_every_allowed_tree_is_refused_not_crashed(tmp_path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    runtime = _runtime(home=home, root=workspace)

    result = _add(runtime, str(outside), workspace)

    assert result["ok"] is False
    assert result["status"] == 403
    assert result["error"] == "path outside home directory"


@pytest.mark.parametrize("target", [{}, ["x"], 17])
def test_a_non_string_path_is_refused_and_never_raises(tmp_path, target):
    """`str({})` is `"{}"` -- a relative name, so it lands under the root.

    The shape does not matter: the jail resolves it like any other relative
    name, the file does not exist, and the answer is a 404 the caller can act
    on. What it must not be is the 500 the fuzzer found, when the second
    check raised `ValueError` for a path outside home.
    """
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()

    path, error, status = resolve_home_path(str(target), root=workspace, home=home)
    assert error is None, (error, status)  # inside the jail: a relative name
    assert path is not None and path.is_relative_to(workspace)

    runtime = _runtime(home=home, root=workspace)
    result = _add(runtime, str(target), workspace)
    assert result["ok"] is False
    assert result["status"] in (400, 403, 404), result


def test_the_two_jails_agree_on_what_is_inside(tmp_path):
    """The property behind the 500: same input, same verdict from both layers.

    Checked rather than argued, because the two call sites drifted once
    already and nothing compared them.
    """
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    (workspace / "inside").mkdir()
    (tmp_path / "outside").mkdir()
    runtime = _runtime(home=home, root=workspace)

    for candidate in (workspace / "inside", home, tmp_path / "outside", tmp_path / "home" / "nope"):
        _path, error, _status = resolve_home_path(str(candidate), root=workspace, home=home)
        jail_says_inside = error is None
        result = _add(runtime, str(candidate), workspace)
        runtime_says_inside = result.get("error") != "path outside home directory"
        assert runtime_says_inside is jail_says_inside, (candidate, error, result)


def test_watcher_rejects_secret_target_and_skips_secret_entries(tmp_path, monkeypatch):
    import os
    if os.name == "nt":
        pytest.skip("symlink creation may require Windows privileges")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("ARENA_AGENT_HOME", str(home))
    (home / ".ssh").mkdir()
    (home / ".ssh" / "hidden").write_text("secret")
    (home / "token.txt").write_text("secret")
    (home / "visible.txt").write_text("ok")
    (home / "alias.txt").symlink_to(home / "token.txt")
    outside = tmp_path / "outside.txt"
    outside.write_text("external")
    (home / "outside-alias.txt").symlink_to(outside)
    runtime = _runtime(home=home, root=home)
    assert _add(runtime, str(home / "token.txt"), home)["status"] == 403
    result = runtime.add_sync(path=str(home), root=home, recursive=True, patterns=[], label="", created_at="now")
    assert result["ok"]
    snapshot = runtime.state["watchers"][result["id"]]["snapshot"]
    assert set(snapshot) == {str(home / "visible.txt")}


def test_snapshot_rechecks_watch_root_after_symlink_is_retargeted(tmp_path, monkeypatch):
    from arena.filewatch.runtime import _snapshot

    home, outside = tmp_path / "home", tmp_path / "outside"
    inside = home / "inside"
    inside.mkdir(parents=True)
    outside.mkdir()
    (inside / "safe.txt").write_text("safe")
    (outside / "private.txt").write_text("private")
    alias = home / "watch"
    try:
        alias.symlink_to(inside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(home))
    first, _ = _snapshot(alias, True, [], 50, root=home, home=home)
    assert str(alias / "safe.txt") in first
    alias.unlink()
    alias.symlink_to(outside, target_is_directory=True)
    second, _ = _snapshot(alias, True, [], 50, root=home, home=home)
    assert second == {}

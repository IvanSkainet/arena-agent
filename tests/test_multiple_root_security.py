"""Sensitivity and execution safeguards apply to all allowed trees."""

import pytest

from arena.files import sandbox


@pytest.fixture
def roots(tmp_path, monkeypatch):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    state = tmp_path / "state"
    for p in (home, workspace, state):
        p.mkdir()
    monkeypatch.setenv("ARENA_AGENT_HOME", str(state))
    return home, workspace, state


def call(verb, target, home, workspace):
    fn = getattr(sandbox, f"validate_{verb}_target")
    kwargs = {"root": workspace, "home": home}
    if verb in {"upload", "edit", "create"}:
        kwargs["bridge_py"] = home / "bridge.py"
    return fn(str(target), **kwargs)


@pytest.mark.parametrize("which", ["workspace", "state"])
@pytest.mark.parametrize("prefix", [".ssh", ".config/gh", "autonomy"])
@pytest.mark.parametrize("verb", ["upload", "edit", "create", "view", "download"])
def test_sensitive_paths_denied_in_each_allowed_tree(roots, which, prefix, verb):
    home, workspace, state = roots
    base = workspace if which == "workspace" else state
    path, error, status = call(verb, base / prefix / "secret", home, workspace)
    assert path is None and status == 403, (verb, which, error, status)


@pytest.mark.parametrize("which", ["workspace", "state"])
@pytest.mark.parametrize("verb", ["upload", "edit", "create"])
def test_executable_directories_cannot_be_written_in_each_tree(roots, which, verb):
    home, workspace, state = roots
    base = workspace if which == "workspace" else state
    path, error, status = call(verb, base / "bin" / "hooks_runner.py", home, workspace)
    assert path is None and status == 403, (verb, which, error, status)


def test_allowed_root_itself_cannot_hide_sensitive_ancestors(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / ".config" / "gh"
    workspace.mkdir(parents=True)
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path / "state"))
    _, _, status = call("view", workspace / "data", home, workspace)
    assert status == 403


def test_ordinary_files_in_both_roots_remain_accessible(roots):
    home, workspace, state = roots
    for base in (workspace, state):
        target = base / "notes.txt"
        target.write_text("hello")
        assert call("view", target, home, workspace)[2] == 200
        assert call("download", target, home, workspace)[2] == 200


def test_http_file_endpoints_enforce_the_policy_outside_home(roots):
    import asyncio
    from urllib.parse import quote

    from tests._live_bridge import auth_header, running_client

    _, workspace, state = roots
    secret = state / ".config" / "gh" / "hosts.yml"
    secret.parent.mkdir(parents=True)
    secret.write_text("not for an agent")
    hook = state / "bin" / "hooks_runner.py"

    async def probe():
        async with running_client(workspace, "security-regression") as client:
            headers = auth_header("security-regression")
            view = await client.post("/v1/fs/view", json={"path": str(secret)}, headers=headers)
            download = await client.get("/v1/download?path=" + quote(str(secret)), headers=headers)
            upload = await client.post("/v1/upload?path=" + quote(str(hook)),
                                       data=b"hostile code", headers=headers)
            return view.status, download.status, upload.status

    assert asyncio.run(probe()) == (403, 403, 403)
    assert not hook.exists()

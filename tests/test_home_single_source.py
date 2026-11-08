"""One answer to "where is home" — and a ratchet that keeps it that way.

Three layers used to answer that question three different ways:

* the bridge's data directory defaulted to **the directory the code lives in**
  (``BRIDGE_DIR``), so a default ``serve`` dropped queue/missions/relay into the
  checkout — and into ``site-packages`` on a pip install;
* every CLI re-derived ``ARENA_AGENT_HOME`` or ``~/arena-bridge`` by hand, in
  twenty separate copies, none of which knew about ``--root``;
* the fs sandbox jailed paths at ``$HOME``, so a bridge started with ``--root``
  outside ``$HOME`` refused to read its own state directory.

These tests pin the single source (``arena/home.py``) and the three failures it
exists to prevent. Each one is written so that re-introducing the old shape
turns it red — that is the whole point of the file, not the coverage number.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARENA = REPO_ROOT / "arena"


# --------------------------------------------------------------- сам источник


def test_agent_home_prefers_an_explicit_value(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path / "env"))
    from arena.home import agent_home

    assert agent_home(tmp_path / "explicit") == tmp_path / "explicit"


def test_agent_home_prefers_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path / "env"))
    from arena.home import agent_home

    assert agent_home() == tmp_path / "env"


def test_agent_home_defaults_to_the_documented_location(monkeypatch):
    monkeypatch.delenv("ARENA_AGENT_HOME", raising=False)
    from arena.home import agent_home

    assert agent_home() == Path.home() / "arena-bridge"


def test_agent_home_is_never_the_code_directory(monkeypatch):
    """The #B-019 regression: state must not land next to the source."""
    monkeypatch.delenv("ARENA_AGENT_HOME", raising=False)
    from arena.home import agent_home, code_root

    root = agent_home()
    assert root != code_root()
    assert code_root() not in root.parents


def test_code_root_holds_the_scripts_the_cli_runs():
    """The #B-029 regression: run_bin looked under the *data* directory."""
    from arena.home import code_root

    assert (code_root() / "bin" / "mcp_marketplace.py").exists()
    assert (code_root() / "arena" / "home.py").exists()


def test_token_path_follows_arena_token_file(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_TOKEN_FILE", str(tmp_path / "custom.token"))
    from arena.home import token_path

    assert token_path() == tmp_path / "custom.token"


# ---------------------------------------------------- больше одной копии быть не должно


def _python_sources():
    """Package sources except the resolver itself — it is the one place allowed."""
    return [
        p for p in ARENA.rglob("*.py")
        if "__pycache__" not in p.parts and p.name != "home.py"
    ]


STANDALONE_HOME = re.compile(r"Path\.home\(\)[\s/]*[,'\"]\s*arena-bridge")
HOME_LITERAL = re.compile(r'Path\.home\(\)\s*/\s*"arena-bridge"')
HOME_ENV = re.compile(r'environ\.get\("ARENA_AGENT_HOME')


def _scan_file(path: Path, pattern: re.Pattern[str]) -> list[str]:
    """Offending lines of one file, as ``file:line`` — no nesting, no early exits."""
    return [
        f"{path.relative_to(REPO_ROOT)}:{number}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line) and not _is_exempt(line)
    ]


def _is_exempt(line: str) -> bool:
    """The one deliberate exception: the historical token location.

    Kept as a last-resort *read* fallback for installs that predate
    ``arena.home``; ``token_path`` documents why.
    """
    return "token.txt" in line or "token_path_for" in line


def _scan(paths: list[Path], pattern: re.Pattern[str]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        hits.extend(_scan_file(path, pattern))
    return hits


def test_no_module_rederives_the_home_directory():
    """A fourth copy of the resolver is how the first three drifted apart."""
    offenders = _scan(_python_sources(), HOME_LITERAL)
    assert not offenders, "дома переопределены мимо arena/home.py: " + ", ".join(offenders)


def test_no_module_reads_arena_agent_home_directly():
    offenders = _scan(_python_sources(), HOME_ENV)
    assert not offenders, (
        "ARENA_AGENT_HOME читается в обход arena/home.py: " + ", ".join(offenders)
    )


def test_paths_are_wired_without_the_code_directory():
    """The exact edit that filled the checkout on a default run."""
    text = (ARENA / "wiring" / "paths_runtime.py").read_text(encoding="utf-8")
    assert "from_env()" in text
    assert 'from_env(g["BRIDGE_DIR"])' not in text


# ------------------------------------------------------------------ песочница


def test_state_directory_is_readable_even_when_the_jail_is_elsewhere(monkeypatch, tmp_path):
    """The #B-030 regression: `--root /tmp/x` blinded the agent to its own queue."""
    home = tmp_path / "data"
    home.mkdir()
    (home / "queue").mkdir()
    (home / "queue" / "job.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(home))

    from arena.files.sandbox import resolve_home_path

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    resolved, err, status = resolve_home_path(
        str(home / "queue" / "job.json"), root=workspace, home=workspace
    )
    assert err is None, err
    assert status == 200
    assert resolved == home / "queue" / "job.json"


def test_the_workspace_root_is_readable_while_home_stays_the_real_home(tmp_path, monkeypatch):
    """The exact B-030 shape: ``serve --root /tmp/x`` with the jail still at ``$HOME``.

    The first test above passes even when ``root`` is dropped from the jail,
    because it happens to read from the state directory. This one is the case
    that was actually broken on a live bridge: the workspace lived outside
    ``$HOME``, so *every* ``/v1/fs/*`` call answered 403 -- including reading
    the workspace the operator had just asked the agent to work in.
    """
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("ARENA_AGENT_HOME", str(state))
    workspace = tmp_path / "workspace-outside-home"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("hello", encoding="utf-8")

    from arena.files.sandbox import resolve_home_path

    resolved, err, status = resolve_home_path(
        str(workspace / "notes.txt"),
        root=workspace,
        home=tmp_path / "the-real-home",
    )
    assert err is None, err
    assert status == 200
    assert resolved == workspace / "notes.txt"


def test_paths_outside_both_roots_are_still_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path / "data"))
    from arena.files.sandbox import resolve_home_path

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _, err, status = resolve_home_path("/etc/passwd", root=workspace, home=workspace)
    assert status == 403
    assert err == "path outside home directory"


def test_the_token_file_stays_blocked_inside_the_state_directory(monkeypatch, tmp_path):
    """Widening the jail must not widen the blocklist."""
    home = tmp_path / "data"
    home.mkdir()
    (home / "token.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(home))

    from arena.files.sandbox import resolve_home_path

    resolved, err, status = resolve_home_path(
        str(home / "token.txt"), root=home, home=home
    )
    # The jail accepts it; the sensitive-basename blocklist is what must refuse.
    assert status == 200 and resolved is not None
    from arena.files.sandbox import _sensitivity_error

    verdict = _sensitivity_error(resolved, home, action="reading")
    assert verdict is not None
    message, status = verdict
    assert status == 403
    assert "token.txt" in message


def test_token_from_an_older_install_is_still_found(monkeypatch, tmp_path):
    """Апгрейд не должен «разлогинивать» клиентов.

    До 4.170.0 токен лежал рядом с ``unified_bridge.py``. Если после обновления
    код ищет только ``~/arena-bridge/token.txt``, он не находит файл, генерирует
    новый — и каждый уже настроенный клиент получает 401.
    """
    from arena import home as home_mod

    new_home = tmp_path / "agent"
    old_code = tmp_path / "code"
    old_code.mkdir()
    (old_code / "token.txt").write_text("legacy-token\n", encoding="utf-8")
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    monkeypatch.setattr(home_mod, "agent_home", lambda *a, **k: new_home)
    monkeypatch.setattr(home_mod, "code_root", lambda: old_code)

    assert home_mod.token_path() == old_code / "token.txt"
    # а запись всегда идёт в новое место, чтобы файл однажды переехал
    assert home_mod.token_path(for_write=True) == new_home / "token.txt"


def test_token_is_not_invented_when_neither_location_has_one(monkeypatch, tmp_path):
    from arena import home as home_mod

    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    monkeypatch.setattr(home_mod, "agent_home", lambda *a, **k: tmp_path / "agent")
    monkeypatch.setattr(home_mod, "code_root", lambda: tmp_path / "code")
    assert home_mod.token_path() == tmp_path / "agent" / "token.txt"


#: Standalone scripts that run without the package importable (`python scripts/x.py`
#: puts `scripts/` on sys.path, not the repo root), so they cannot call
#: ``agent_home()`` and keep their own copy of the default. Pinned here rather than
#: left free-floating: a new copy fails the ratchet, and the list shrinking is
#: welcome. Deleting an entry is only correct once the script imports the package.
STANDALONE_HOME_COPIES = {
    "bin/agentctl_tui.py",
    "bin/agents_md.py",
    "bin/hooks_runner.py",
    "bin/skill_from_sub.py",
    "bin/subagent.py",
    "bin/web_gateway.py",
    "scripts/audit_tool.py",
    "scripts/backup_tool.py",
    "scripts/check_bridge.py",
    "scripts/chat_append.py",
    "scripts/file_agent_loop.py",
    "scripts/mcp_manager.py",
    "scripts/recon_report.py",
    "scripts/report_tools.py",
    "scripts/superpowers_lite.py",
    "scripts/superpowers_manager.py",
    "scripts/task_maintenance.py",
    "scripts/task_runner.py",
}


def test_standalone_scripts_do_not_grow_new_home_copies():
    """Scripts may lag the resolver; they may not multiply it.

    ``arena/`` is held at zero copies. This is the second ring: 16 standalone
    scripts that predate :mod:`arena.home` and run outside the package. They are
    allowed to keep their copy, and forbidden to gain a friend -- a quiet
    re-growth of the same drift, one helper script at a time, is exactly how the
    first four copies appeared.
    """
    bases = [REPO_ROOT / "scripts", REPO_ROOT / "bin"]
    sources = [p for base in bases for p in sorted(base.rglob("*.py")) if "__pycache__" not in p.parts]
    offenders = [
        hit for hit in _scan(sources, STANDALONE_HOME) if hit.split(":")[0] not in STANDALONE_HOME_COPIES
    ]
    assert not offenders, (
        "новые копии резолвера в standalone-скриптах: "
        + ", ".join(offenders)
        + " — импортируйте arena.home (или добавьте файл в STANDALONE_HOME_COPIES с обоснованием)"
    )


def test_the_standalone_debt_list_has_no_stale_entries():
    """A pinned list that nobody prunes becomes a lie of its own."""
    stale = []
    for rel in sorted(STANDALONE_HOME_COPIES):
        path = REPO_ROOT / rel
        if not path.exists():
            stale.append(f"{rel} (файла нет)")
        elif "arena-bridge" not in path.read_text(encoding="utf-8"):
            stale.append(f"{rel} (копии больше нет)")
    assert not stale, "STANDALONE_HOME_COPIES устарел: " + ", ".join(stale)

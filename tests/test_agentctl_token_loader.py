"""Tests for the v4.41.0 token-loader priority fix (audit
finding #8).

Pre-v4.41.0 order was: ARENA_TOKEN_FILE > disk (~/arena-bridge/
token.txt) > ARENA_BRIDGE_TOKEN env. That meant a stale disk
token silently overrode a freshly-exported env var, which was
surprising and made scripted overrides impossible. v4.41.0
promotes env above disk while keeping disk-only setups working.

New order under test:
  1. ARENA_TOKEN_FILE explicit file
  2. ARENA_BRIDGE_TOKEN env var
  3. $ARENA_AGENT_HOME/token.txt
  4. ~/arena-bridge/token.txt
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def loader(monkeypatch, tmp_path):
    """Reload agentctl_common with a controlled environment so
    module-level ``BRIDGE_TOKEN`` gets re-computed each test.

    Isolation levers used, in order of importance:

    * ``ARENA_AGENT_HOME`` points at a per-test tmp dir so
      the 3rd priority level (``$ARENA_AGENT_HOME/token.txt``)
      is fully controlled.
    * ``HOME`` is also monkeypatched to the same tmp dir so
      the 4th priority level (``~/arena-bridge/token.txt``,
      the hardcoded fallback for non-standard
      ``ARENA_AGENT_HOME``) never accidentally picks up a real
      token from the developer's or live bridge's home. Without
      this, the ``test_empty_disk_falls_through`` test would
      pass on a laptop but fail on the CachyOS box where a real
      ``~ivan/arena-bridge/token.txt`` exists.
    * ``ARENA_TOKEN_FILE`` and ``ARENA_BRIDGE_TOKEN`` are
      cleared so each test starts from the same env baseline.
    """
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    monkeypatch.delenv("ARENA_BRIDGE_TOKEN", raising=False)
    import arena.agentctl_cli.agentctl_common as m
    importlib.reload(m)
    return m


def _reload_after_env_change(loader_mod):
    """Repeat the reload once the test has mutated env, so the
    module-level constants pick up the change. Cleaner than
    calling loader_mod._load_token() directly because we're
    actually testing the module's boot path."""
    importlib.reload(loader_mod)
    return loader_mod._load_token()


def test_explicit_file_wins_over_everything(loader, tmp_path, monkeypatch):
    home_tok = tmp_path / "token.txt"
    home_tok.write_text("HOME_TOKEN")
    monkeypatch.setenv("ARENA_BRIDGE_TOKEN", "ENV_TOKEN")
    explicit = tmp_path / "explicit.txt"
    explicit.write_text("EXPLICIT_TOKEN")
    monkeypatch.setenv("ARENA_TOKEN_FILE", str(explicit))
    assert _reload_after_env_change(loader) == "EXPLICIT_TOKEN"


def test_env_wins_over_disk_v4_41_fix(loader, tmp_path, monkeypatch):
    """The v4.41.0 fix: env now beats disk. Pre-v4.41.0 this
    would have returned HOME_TOKEN, silently ignoring the
    operator's ARENA_BRIDGE_TOKEN override."""
    home_tok = tmp_path / "token.txt"
    home_tok.write_text("HOME_TOKEN")
    monkeypatch.setenv("ARENA_BRIDGE_TOKEN", "ENV_TOKEN")
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    assert _reload_after_env_change(loader) == "ENV_TOKEN"


def test_disk_used_when_env_unset(loader, tmp_path, monkeypatch):
    """No env -> disk fallback still works. This is the default
    single-user install path and must stay unchanged."""
    home_tok = tmp_path / "token.txt"
    home_tok.write_text("HOME_TOKEN")
    monkeypatch.delenv("ARENA_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    assert _reload_after_env_change(loader) == "HOME_TOKEN"


def test_empty_env_falls_through_to_disk(loader, tmp_path, monkeypatch):
    """An operator with ``export ARENA_BRIDGE_TOKEN=""`` in
    their rc (common mistake) should still get the disk token,
    not an empty string that fails every subsequent 401."""
    home_tok = tmp_path / "token.txt"
    home_tok.write_text("HOME_TOKEN")
    monkeypatch.setenv("ARENA_BRIDGE_TOKEN", "")
    assert _reload_after_env_change(loader) == "HOME_TOKEN"


def test_empty_disk_falls_through(loader, tmp_path, monkeypatch):
    """Empty file must NOT be treated as a valid empty token --
    otherwise every request fails 401 with no diagnostic. We
    return empty string only when literally nothing was
    resolvable."""
    home_tok = tmp_path / "token.txt"
    home_tok.write_text("")
    monkeypatch.delenv("ARENA_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    assert _reload_after_env_change(loader) == ""


def test_multiline_disk_returns_first_non_empty_line(loader, tmp_path,
                                                     monkeypatch):
    """token.txt sometimes has a trailing newline plus a
    provenance comment (some install scripts do this). Only the
    first non-empty line counts as the token."""
    home_tok = tmp_path / "token.txt"
    home_tok.write_text("\n\nFIRST_REAL_LINE\n# provenance: ...\n")
    monkeypatch.delenv("ARENA_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    assert _reload_after_env_change(loader) == "FIRST_REAL_LINE"


def test_missing_explicit_file_falls_through_to_env(loader, tmp_path,
                                                    monkeypatch):
    """ARENA_TOKEN_FILE set but the file doesn't exist -- treated
    as "no explicit file" and we fall through to env. Pre-fix
    this would have skipped straight to disk, which had the same
    surprise semantics as #8."""
    monkeypatch.setenv("ARENA_TOKEN_FILE", str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("ARENA_BRIDGE_TOKEN", "ENV_WINS")
    (tmp_path / "token.txt").write_text("DISK_SHOULD_LOSE")
    assert _reload_after_env_change(loader) == "ENV_WINS"


def test_all_sources_absent_returns_empty(loader, tmp_path, monkeypatch):
    monkeypatch.delenv("ARENA_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    # Also ensure ~/arena-bridge/token.txt doesn't exist by
    # pointing HOME at tmp_path.
    monkeypatch.setenv("HOME", str(tmp_path))
    assert _reload_after_env_change(loader) == ""

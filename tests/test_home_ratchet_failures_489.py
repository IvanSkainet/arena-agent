"""Bilateral controls for the new path-source and standalone-debt gates."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import TestCase

import pytest

CHECK = TestCase()
SOURCE = Path(__file__).with_name("test_home_single_source.py")


def _gate():
    spec = importlib.util.spec_from_file_location("home_gate_under_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("expression", ['os.environ.get("ARENA_AGENT_HOME", "fallback")',
                                            "os.environ.get('ARENA_AGENT_HOME')",
                                            'os.environ["ARENA_AGENT_HOME"]',
                                            'os.getenv("ARENA_AGENT_HOME")'])
def test_env_scan_rejects_each_supported_access_form(tmp_path, monkeypatch, expression):
    gate = _gate()
    source = tmp_path / "regression.py"
    source.write_text(expression)
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gate, "_python_sources", lambda: [source])
    with pytest.raises(AssertionError, match="ARENA_AGENT_HOME"):
        gate.test_no_module_reads_arena_agent_home_directly()


@pytest.mark.parametrize("literal", ['"arena-bridge"', "'arena-bridge'"])
def test_home_literal_scan_rejects_a_new_copy_even_on_a_token_line(tmp_path, monkeypatch, literal):
    gate = _gate()
    source = tmp_path / "regression.py"
    source.write_text(f"value = Path.home() / {literal}  # token.txt\n")
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gate, "_python_sources", lambda: [source])
    with pytest.raises(AssertionError, match="regression.py"):
        gate.test_no_module_rederives_the_home_directory()


def test_standalone_gate_rejects_a_new_script(tmp_path, monkeypatch):
    gate = _gate()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "regression.py").write_text('ROOT = Path.home() / "arena-bridge"\n')
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    with pytest.raises(AssertionError, match="scripts/regression.py"):
        gate.test_standalone_scripts_do_not_grow_new_home_copies()


def test_standalone_debt_entry_is_not_kept_alive_by_a_comment(tmp_path, monkeypatch):
    gate = _gate()
    source = tmp_path / "example.py"
    source.write_text('# arena-bridge used to be here\nvalue = 1\n')
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gate, "STANDALONE_HOME_COPIES", {"example.py"})
    with pytest.raises(AssertionError, match="example.py"):
        gate.test_the_standalone_debt_list_has_no_stale_entries()


def test_path_wiring_gate_rejects_a_return_to_code_root(tmp_path, monkeypatch):
    gate = _gate()
    source = tmp_path / "arena/wiring/paths_runtime.py"
    source.parent.mkdir(parents=True)
    source.write_text('paths = g["ArenaPaths"].from_env(g["BRIDGE_DIR"])\n')
    monkeypatch.setattr(gate, "ARENA", tmp_path / "arena")
    with pytest.raises(AssertionError):
        gate.test_paths_are_wired_without_the_code_directory()

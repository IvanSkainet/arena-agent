"""v4.169.35 -- agentctl memory/recall parity tests (mutation-driven).

Pins all CLI behaviors in `arena/agentctl_cli/agentctl_memory.py`:
* `_arg_value` and `_remove_flag` edge cases;
* `mem_set` CLI validation, profile/tag parsing, bridge payload, and output formatting;
* `mem_get` query normalization ('all' -> ''), profile URL encoding, fact list formatting, and error paths;
* `recall_search` query extraction, score formatting (:.2f), fact fallback, and error handling;
* `recall_digest` digest extraction vs json fallback formatting.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.agentctl_cli.agentctl_memory as mem_cli  # noqa: E402


# --------------------------------------------------------------------
# 1. Helpers: _arg_value and _remove_flag
# --------------------------------------------------------------------
def test_arg_value():
    assert mem_cli._arg_value(["--profile", "proj", "extra"], "--profile") == "proj"
    assert mem_cli._arg_value(["--profile"], "--profile") is None
    assert mem_cli._arg_value(["other", "args"], "--profile") is None


def test_remove_flag_middle_elements():
    args = ["arg0", "arg1", "--profile", "val", "arg2", "arg3"]
    assert mem_cli._remove_flag(args, "--profile") == ["arg0", "arg1", "arg2", "arg3"]
    assert mem_cli._remove_flag(["k", "v", "--profile"], "--profile") == ["k", "v"]
    assert mem_cli._remove_flag(["k", "v"], "--profile") == ["k", "v"]


# --------------------------------------------------------------------
# 2. mem_set
# --------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_args",
    [
        [],
        ["single_arg"],
        ["--profile", "myprof"],
        ["--tags", "t1", "t2"],
        ["k", "--tags", "t1"],
    ],
)
def test_mem_set_invalid_args_exits(bad_args, capsys):
    with pytest.raises(SystemExit) as exc:
        mem_cli.mem_set(bad_args)
    assert exc.value.code == 2
    assert (
        capsys.readouterr().out
        == "Usage: agentctl mem set KEY VALUE [--tags tag1 tag2] [--profile PROFILE]\n"
    )


def test_mem_set_happy_path(monkeypatch, capsys):
    captured = {}

    def _fake_post(path, data):
        captured["path"] = path
        captured["data"] = data
        return {"ok": True, "fact_id": "123"}

    monkeypatch.setattr(mem_cli, "bridge_post", _fake_post)
    mem_cli.mem_set(["mykey", "myvalue", "--tags", "tag1", "tag2", "--profile", "work"])

    assert captured["path"] == "/v1/memory"
    assert captured["data"] == {
        "profile": "work",
        "key": "mykey",
        "value": "myvalue",
        "tags": ["tag1", "tag2"],
    }
    assert capsys.readouterr().out == "OK: {'ok': True, 'fact_id': '123'}\n"


def test_mem_set_failure_and_default_profile(monkeypatch, capsys):
    captured = {}

    def _fake_post(path, data):
        captured["path"] = path
        captured["data"] = data
        return {"ok": False, "error": "database locked"}

    monkeypatch.setattr(mem_cli, "bridge_post", _fake_post)
    mem_cli.mem_set(["k", "v"])

    assert captured["data"]["profile"] == "default"
    assert captured["data"]["tags"] == []
    assert capsys.readouterr().out == "FAIL: {'ok': False, 'error': 'database locked'}\n"


def test_mem_set_exception_handling(monkeypatch, capsys):
    def _raise_post(path, data):
        raise ConnectionError("bridge unreachable")

    monkeypatch.setattr(mem_cli, "bridge_post", _raise_post)
    mem_cli.mem_set(["k", "v"])
    assert capsys.readouterr().out == "Error: bridge unreachable\n"


# --------------------------------------------------------------------
# 3. mem_get
# --------------------------------------------------------------------
def test_mem_get_all_query_normalization(monkeypatch, capsys):
    captured = {}

    def _fake_get(url):
        captured["url"] = url
        return {
            "count": 2,
            "profile": "custom",
            "facts": [
                {"key": "user_name", "value": "Alice"},
                {"key": "long_fact", "value": "x" * 100},
            ],
        }

    monkeypatch.setattr(mem_cli, "bridge_get", _fake_get)
    mem_cli.mem_get(["all", "--profile", "my profile"])

    assert captured["url"] == "/v1/memory?profile=my%20profile&q="
    out = capsys.readouterr().out
    expected = (
        "Facts (2) in profile custom:\n"
        "  user_name: Alice\n"
        f"  long_fact: {'x' * 80}\n"
    )
    assert out == expected


def test_mem_get_query_and_empty_facts(monkeypatch, capsys):
    captured = {}

    def _fake_get(url):
        captured["url"] = url
        return {"count": 0, "profile": "personal", "facts": []}

    monkeypatch.setattr(mem_cli, "bridge_get", _fake_get)
    mem_cli.mem_get(["needle"])

    assert captured["url"] == "/v1/memory?profile=default&q=needle"
    assert capsys.readouterr().out == "Facts (0) in profile personal:\n"


def test_mem_get_missing_keys_in_facts(monkeypatch, capsys):
    captured = {}

    def _fake_get(url):
        captured["url"] = url
        return {"facts": [{}]}

    monkeypatch.setattr(mem_cli, "bridge_get", _fake_get)
    mem_cli.mem_get([])

    assert captured["url"] == "/v1/memory?profile=default&q="
    assert capsys.readouterr().out == "Facts (0) in profile default:\n  ?: \n"


def test_mem_get_exception(monkeypatch, capsys):
    def _raise_get(url):
        raise TimeoutError("timed out")

    monkeypatch.setattr(mem_cli, "bridge_get", _raise_get)
    mem_cli.mem_get([])
    assert capsys.readouterr().out == "Error: timed out\n"


# --------------------------------------------------------------------
# 4. recall_search
# --------------------------------------------------------------------
def test_mem_get_query_with_profile_and_flag_removal(monkeypatch, capsys):
    captured = {}

    def _fake_get(url):
        captured["url"] = url
        return {"count": 1, "profile": "proj", "facts": [{"key": "k", "value": "v"}]}

    monkeypatch.setattr(mem_cli, "bridge_get", _fake_get)
    mem_cli.mem_get(["--profile", "proj", "search_term"])

    assert captured["url"] == "/v1/memory?profile=proj&q=search_term"
    assert capsys.readouterr().out == "Facts (1) in profile proj:\n  k: v\n"


def test_recall_search_nested_fact_and_score_formatting(monkeypatch, capsys):
    captured = {}

    def _fake_get(url):
        captured["url"] = url
        return {
            "count": 1,
            "profile": "work",
            "facts": [
                {
                    "score": 0.854,
                    "fact": {"key": "goal", "value": "x" * 100},
                }
            ],
        }

    monkeypatch.setattr(mem_cli, "bridge_get", _fake_get)
    mem_cli.recall_search(["--profile", "work", "query string"])

    assert captured["url"] == "/v1/recall?profile=work&q=query%20string"
    out = capsys.readouterr().out
    assert "Recall (1) in profile work:\n" in out
    assert f"  [0.85] goal: {'x' * 80}\n" in out
    assert ("x" * 81) not in out


def test_recall_digest_default_profile(monkeypatch, capsys):
    captured = {}

    def _fake_get(url):
        captured["url"] = url
        return {"digest": "default summary"}

    monkeypatch.setattr(mem_cli, "bridge_get", _fake_get)
    mem_cli.recall_digest([])

    assert captured["url"] == "/v1/recall/digest?profile=default"
    assert capsys.readouterr().out == "default summary\n"


def test_recall_search_flat_fact_fallback_and_defaults(monkeypatch, capsys):
    captured = {}

    def _fake_get(url):
        captured["url"] = url
        return {
            "facts": [
                {"score": 1.0, "key": "flat_key", "value": "flat_val"},
                {},  # missing score, key, value
            ],
        }

    monkeypatch.setattr(mem_cli, "bridge_get", _fake_get)
    mem_cli.recall_search([])

    assert captured["url"] == "/v1/recall?profile=default&q="
    expected = (
        "Recall (0) in profile default:\n"
        "  [1.00] flat_key: flat_val\n"
        "  [0.00] ?: \n"
    )
    assert capsys.readouterr().out == expected


def test_recall_search_exception(monkeypatch, capsys):
    def _raise_get(url):
        raise RuntimeError("database corrupt")

    monkeypatch.setattr(mem_cli, "bridge_get", _raise_get)
    mem_cli.recall_search([])
    assert capsys.readouterr().out == "Error: database corrupt\n"


# --------------------------------------------------------------------
# 5. recall_digest
# --------------------------------------------------------------------
def test_recall_digest_with_digest_field(monkeypatch, capsys):
    captured = {}

    def _fake_get(url):
        captured["url"] = url
        return {"digest": "Key facts:\n- operator: Ivan\n- version: 4.169.35"}

    monkeypatch.setattr(mem_cli, "bridge_get", _fake_get)
    mem_cli.recall_digest(["--profile", "prod"])

    assert captured["url"] == "/v1/recall/digest?profile=prod"
    assert capsys.readouterr().out == "Key facts:\n- operator: Ivan\n- version: 4.169.35\n"


def test_recall_digest_json_fallback(monkeypatch, capsys):
    def _fake_get(url):
        return {"raw_summary": "привет", "status": "ok"}

    monkeypatch.setattr(mem_cli, "bridge_get", _fake_get)
    mem_cli.recall_digest([])

    out = capsys.readouterr().out
    expected = json.dumps({"raw_summary": "привет", "status": "ok"}, indent=2, ensure_ascii=False) + "\n"
    assert out == expected


def test_recall_digest_exception(monkeypatch, capsys):
    def _raise_get(url):
        raise ValueError("bad response")

    monkeypatch.setattr(mem_cli, "bridge_get", _raise_get)
    mem_cli.recall_digest([])
    assert capsys.readouterr().out == "Error: bad response\n"

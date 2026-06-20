"""agentctl memory command regressions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.agentctl_cli import agentctl_memory  # noqa: E402


def test_mem_set_passes_profile(monkeypatch, capsys):
    payload = {}

    def _post(path, data, token=True, timeout=20):
        payload.update({"path": path, "data": data})
        return {"ok": True}

    monkeypatch.setattr(agentctl_memory, "bridge_post", _post)
    agentctl_memory.mem_set(["k", "v", "--profile", "projects/arena"])
    assert payload["path"] == "/v1/memory"
    assert payload["data"]["profile"] == "projects/arena"


def test_recall_search_reads_profile_aware_facts(monkeypatch, capsys):
    def _get(path, token=True, timeout=15):
        return {"count": 1, "profile": "personal", "facts": [{"score": 0.5, "fact": {"key": "k", "value": "v"}}]}

    monkeypatch.setattr(agentctl_memory, "bridge_get", _get)
    agentctl_memory.recall_search(["hello", "--profile", "personal"])
    out = capsys.readouterr().out
    assert "profile personal" in out
    assert "k: v" in out

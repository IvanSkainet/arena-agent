"""Resource listing helper tests."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.resources.listing import list_agents, list_hooks, list_missions, list_reports, list_subagents, show_mission  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_list_missions_and_show(tmp_path):
    d = tmp_path / "missions"
    d.mkdir()
    (d / "demo.md").write_text("hello", encoding="utf-8")
    missions = list_missions(d)
    assert missions[0]["name"] == "demo"
    shown = show_mission(d, "demo")
    assert shown["ok"] is True
    assert shown["content"] == "hello"
    assert show_mission(d, "../x")["ok"] is False


def test_list_reports(tmp_path):
    d = tmp_path / "reports"
    shots = d / "shots"
    shots.mkdir(parents=True)
    (d / "a.txt").write_text("a", encoding="utf-8")
    (shots / "b.png").write_text("b", encoding="utf-8")
    names = {r["name"] for r in list_reports(d)}
    assert "a.txt" in names
    assert "shots/b.png" in names


def test_list_hooks_agents_subagents(tmp_path):
    hooks = tmp_path / "hooks"; agents = tmp_path / "agents"; subs = tmp_path / "subagents"
    hooks.mkdir(); agents.mkdir(); subs.mkdir()
    (hooks / "h.json").write_text(json.dumps({"event": "x", "description": "desc"}), encoding="utf-8")
    (agents / "a.json").write_text(json.dumps({"description": "agent", "model": "m"}), encoding="utf-8")
    (subs / "s.json").write_text(json.dumps({"status": "ok", "cmd": "run"}), encoding="utf-8")
    assert list_hooks(hooks)["hooks"][0]["event"] == "x"
    assert list_agents(agents)["agents"][0]["model"] == "m"
    assert list_subagents(subs)["subagents"][0]["status"] == "ok"


def test_unified_bridge_resource_wrappers():
    assert isinstance(ub._list_reports_sync(), list)
    assert ub._hooks_list_sync()["ok"] is True

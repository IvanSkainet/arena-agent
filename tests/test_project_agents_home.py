"""The project agents CLI must use the configured agent home."""
from arena.project_cli.agents import agents_md_command


def test_agents_init_and_show_use_agent_home(tmp_path, monkeypatch, capsys):
    home = tmp_path / "state"
    project = home / "projects" / "example"
    project.mkdir(parents=True)
    (home / "current_project").write_text("example")
    docs = home / "docs"
    docs.mkdir()
    (docs / "AGENTS.md.template").write_text("Project {name}")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(home))
    monkeypatch.delenv("ARENA_CURRENT_PROJECT", raising=False)

    assert agents_md_command(["init"]) == 0
    assert (project / "AGENTS.md").read_text() == "Project example"
    assert agents_md_command(["show"]) == 0
    assert "Project example" in capsys.readouterr().out


def test_agents_discovers_most_recent_project(tmp_path, monkeypatch, capsys):
    home = tmp_path / "state"
    project = home / "projects" / "example"
    project.mkdir(parents=True)
    (project / "AGENTS.md").write_text("Discovered")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(home))
    monkeypatch.delenv("ARENA_CURRENT_PROJECT", raising=False)

    assert agents_md_command(["show"]) == 0
    assert "Discovered" in capsys.readouterr().out

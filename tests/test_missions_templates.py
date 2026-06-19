"""Mission template regressions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.missions_cli.templates import TEMPLATES_DATA, commands_for  # noqa: E402


def test_cli_agent_core_template_no_longer_mentions_backup():
    mission = TEMPLATES_DATA["cli-agent-core"]
    assert "backup" not in mission["goal"].lower()
    assert all("backup" not in step.lower() for step in mission["steps"])
    assert all("backup" not in cmd.lower() for cmd in commands_for("cli-agent-core"))


def test_recovery_drill_template_no_longer_mentions_backup():
    mission = TEMPLATES_DATA["recovery-drill"]
    assert all("backup" not in step.lower() for step in mission["steps"])
    assert all("backup" not in cmd.lower() for cmd in commands_for("recovery-drill"))

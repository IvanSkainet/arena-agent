"""agentctl misc-command regressions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.agentctl_cli import agentctl_common, agentctl_main, agentctl_misc  # noqa: E402
from arena.constants import VERSION  # noqa: E402


def test_agentctl_uses_canonical_bridge_version():
    assert agentctl_common.VERSION == VERSION


def test_backup_run_prints_removed_feature_notice(capsys):
    agentctl_misc.backup_run([])
    out = capsys.readouterr().out
    assert "removed" in out.lower()
    assert "external backup tools" in out.lower()


def test_agentctl_help_mentions_removed_backup_feature(capsys):
    agentctl_main.commands([])
    out = capsys.readouterr().out
    assert "Removed backup feature notice" in out

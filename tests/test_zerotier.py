"""ZeroTier network admin regressions."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.admin.zerotier import zerotier_status, zerotier_network_action


def test_zerotier_status_without_cli():
    """Test zerotier_status when zerotier-cli is not installed."""
    def subprocess_kwargs():
        return {"timeout": 5}

    result = zerotier_status(subprocess_kwargs=subprocess_kwargs)
    assert result["ok"] is True
    assert "zerotier" in result
    # Either error about not found or actual status
    assert "error" in result["zerotier"] or "status" in result["zerotier"]
    assert "networks" in result


def test_zerotier_network_action_invalid():
    """Test zerotier_network_action with invalid action."""
    result = zerotier_network_action("invalid", None)
    assert result["ok"] is False
    assert "action must be" in result["error"]


def test_zerotier_network_action_join_without_id():
    """Test zerotier_network_action join without network_id."""
    result = zerotier_network_action("join", None)
    assert result["ok"] is False
    assert "network_id required" in result["error"]


def test_zerotier_network_action_leave_without_id():
    """Test zerotier_network_action leave without network_id."""
    result = zerotier_network_action("leave", None)
    assert result["ok"] is False
    assert "network_id required" in result["error"]


def test_zerotier_network_action_status_without_cli():
    """Test zerotier_network_action status when zerotier-cli is not installed."""
    result = zerotier_network_action("status", None)
    # Either ok with empty networks or error about binary not found
    if result["ok"]:
        assert "networks" in result
    else:
        assert "not found" in result["error"].lower()

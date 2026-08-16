import pytest
import hmac
from arena.multiagent.agents import AgentRegistry

def test_resolve_token_uses_constant_time_comparison(monkeypatch):
    registry = AgentRegistry()
    registry._by_token = {
        "token_a": "agent_1",
        "token_b": "agent_2"
    }
    registry._by_id = {
        "agent_1": "mock_agent_1",
        "agent_2": "mock_agent_2"
    }
    call_count = 0
    def mock_compare_digest(a, b):
        nonlocal call_count
        call_count += 1
        return a == b
    monkeypatch.setattr(hmac, 'compare_digest', mock_compare_digest)
    result = registry.resolve_token("token_a")
    assert call_count > 0
    assert result == "mock_agent_1"
    call_count = 0
    result = registry.resolve_token("invalid_token")
    assert call_count == 2
    assert result is None

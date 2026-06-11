"""User store tests."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.auth.users import UserStore  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_user_store_load_add_remove(tmp_path):
    path = tmp_path / "users.json"
    store = UserStore(path)
    assert store.load_users() == {}
    store.add_or_update_user(name="alice", token="tok", role="user")
    users = store.load_users()
    assert users["tok"]["name"] == "alice"
    assert users["tok"]["role"] == "user"
    assert store.remove_user("alice") is True
    assert store.remove_user("alice") is False


def test_unified_bridge_user_wrappers():
    assert callable(ub._load_users)
    assert callable(ub.check_auth_with_role)

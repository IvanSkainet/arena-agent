"""Multi-user token store and role checks."""
from __future__ import annotations

import hmac
import json
import threading
import time
from pathlib import Path
from typing import Any

from aiohttp import web
from arena.app_keys import APP_CFG

ROLE_LEVEL = {"admin": 3, "user": 2, "readonly": 1}


class UserStore:
    def __init__(self, users_file: Path, *, log_warning=None, log_debug=None, ttl: float = 5.0):
        self.users_file = users_file
        self.ttl = ttl
        self._cache: dict[str, Any] = {"last_load": 0.0, "users": {}}
        self._lock = threading.Lock()
        self._log_warning = log_warning
        self._log_debug = log_debug

    def invalidate(self) -> None:
        with self._lock:
            self._cache = {"last_load": 0.0, "users": {}}

    def load_users(self) -> dict[str, dict[str, str]]:
        now = time.time()
        with self._lock:
            if (now - self._cache["last_load"]) < self.ttl and self._cache["users"]:
                return self._cache["users"]
        users: dict[str, dict[str, str]] = {}
        if self.users_file.exists():
            try:
                data = json.loads(self.users_file.read_text(encoding="utf-8"))
                for user in data.get("users", []):
                    token = user.get("token", "")
                    if token:
                        users[token] = {"role": user.get("role", "user"), "name": user.get("name", "unknown")}
                with self._lock:
                    self._cache["users"] = users
                    self._cache["last_load"] = now
                if self._log_debug:
                    self._log_debug("[Auth] Loaded %d users from %s", len(users), self.users_file)
            except Exception as exc:
                if self._log_warning:
                    self._log_warning("[Auth] Failed to load users.json: %s", exc)
        return users

    def read_users_data(self) -> dict[str, Any]:
        if self.users_file.exists():
            try:
                return json.loads(self.users_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"users": []}

    def write_users_data(self, data: dict[str, Any]) -> None:
        self.users_file.parent.mkdir(parents=True, exist_ok=True)
        self.users_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self.invalidate()

    def check_auth_with_role(self, request: web.Request, required_role: str | None = None) -> tuple[bool, str]:
        users = self.load_users()
        auth_header = request.headers.get("Authorization", "")
        xt_header = request.headers.get("X-Arena-Token", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        elif xt_header:
            token = xt_header

        if users:
            for stored_token, user_info in users.items():
                if hmac.compare_digest(token, stored_token):
                    user_role = user_info.get("role", "user")
                    if required_role and ROLE_LEVEL.get(user_role, 0) < ROLE_LEVEL.get(required_role, 0):
                        return False, user_role
                    return True, user_role

        cfg_token = request.app[APP_CFG]["token"]
        if token and hmac.compare_digest(token, cfg_token):
            return True, "admin"
        return False, ""

    def list_users_for_response(self, primary_token: str) -> list[dict[str, Any]]:
        users = self.load_users()
        user_list = [
            {"name": info.get("name", "unknown"), "role": info.get("role", "user"), "token_length": len(token)}
            for token, info in users.items()
        ]
        user_list.insert(0, {"name": "primary_admin", "role": "admin", "token_length": len(primary_token)})
        return user_list

    def add_or_update_user(self, *, name: str, token: str, role: str) -> None:
        data = self.read_users_data()
        data.setdefault("users", [])
        updated = False
        for user in data["users"]:
            if user.get("name") == name:
                user["role"] = role
                user["token"] = token
                updated = True
                break
        if not updated:
            data["users"].append({"token": token, "role": role, "name": name})
        self.write_users_data(data)

    def remove_user(self, name: str) -> bool:
        data = self.read_users_data()
        data.setdefault("users", [])
        before = len(data["users"])
        data["users"] = [user for user in data["users"] if user.get("name") != name]
        if len(data["users"]) == before:
            return False
        self.write_users_data(data)
        return True

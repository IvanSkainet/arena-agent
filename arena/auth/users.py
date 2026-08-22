"""Multi-user token store and role checks."""
from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from arena.app_keys import APP_CFG
from arena.auth.compare import secrets_equal

ROLE_LEVEL = {"admin": 3, "user": 2, "readonly": 1}


class UsersFileCorrupt(RuntimeError):
    """The user file exists but cannot be parsed.

    Raised instead of quietly reporting an empty roster, so a damaged
    file fails closed rather than being overwritten with a fresh one.
    """


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
            # v4.169.49 (#63): "no users" is a cacheable answer. The TTL
            # check used to also require a non-empty roster, so a bridge
            # with an empty users.json re-read and re-parsed the file on
            # every single auth check -- measured at 100 reads per 100
            # calls, versus 1 per 100 once a user exists. `invalidate()`
            # resets `last_load` to 0.0, so an emptied roster is still
            # picked up immediately; emptiness never needed to defeat the
            # cache to stay correct.
            if (now - self._cache["last_load"]) < self.ttl:
                return self._cache["users"]
        users: dict[str, dict[str, str]] = {}
        if not self.users_file.exists():
            # "no file" is cacheable for the same reason "no users" is:
            # otherwise every auth check stats the filesystem. Creating a
            # roster goes through `write_users_data`, which invalidates.
            with self._lock:
                self._cache["users"] = users
                self._cache["last_load"] = now
            return users
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
            # A damaged file is NOT cached: retrying next call is the
            # right behaviour for a roster someone may be repairing.
            if self._log_warning:
                self._log_warning("[Auth] Failed to load users.json: %s", exc)
        return users

    def read_users_data(self) -> dict[str, Any]:
        """Parsed user file, or `{"users": []}` when there genuinely is none.

        v4.166.3 (bug #74): "unreadable" and "empty" used to be the same
        answer. A file that exists but does not parse is not an empty
        roster -- it is a damaged one -- and returning `{"users": []}`
        for it made `add_or_update_user` rebuild the file from that empty
        list, converting a recoverable corruption into a permanent one.

        A missing file is still an empty roster: that is first-run.
        """
        if not self.users_file.exists():
            return {"users": []}
        try:
            data = json.loads(self.users_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UsersFileCorrupt(
                f"{self.users_file} exists but could not be read: {exc}. "
                f"Refusing to treat it as an empty user list; a rewrite "
                f"would discard every account in it."
            ) from exc
        if not isinstance(data, dict):
            raise UsersFileCorrupt(
                f"{self.users_file} holds {type(data).__name__}, not an object")
        return data

    def write_users_data(self, data: dict[str, Any]) -> None:
        """Replace the user file atomically.

        v4.166.3 (bug #74): this was a bare `write_text`, which truncates
        the destination and then writes. A crash, a full disk, or a
        kill -9 in that window leaves a half-written file, and the reader
        above turned that into "no users at all".

        Measured on the unfixed pair: 60 accounts, the file truncated to
        60% of its length, and every account was gone -- `load_users()`
        returned `{}` and the next `add_or_update_user` wrote a file with
        a single entry. Sixty tokens deleted by one interrupted write.

        Write to a temp file in the same directory, flush and fsync it,
        then `os.replace`. `os.replace` is atomic on POSIX and Windows
        alike, so a reader sees either the old file or the new one and
        never a torn one -- the same reasoning as bug #73's claim.
        """
        self.users_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        tmp = self.users_file.with_name(self.users_file.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(payload)
                # Durability, not just atomicity: os.replace only promises
                # that the rename is atomic, not that the bytes reached the
                # disk before it. Without the fsync a power loss can land
                # the rename and lose the contents.
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.users_file)
        except OSError:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise
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
                if secrets_equal(token, stored_token):
                    user_role = user_info.get("role", "user")
                    if required_role and ROLE_LEVEL.get(user_role, 0) < ROLE_LEVEL.get(required_role, 0):
                        return False, user_role
                    return True, user_role

        cfg_token = request.app[APP_CFG]["token"]
        if token and secrets_equal(token, cfg_token):
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

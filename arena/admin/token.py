"""Admin token management helpers."""
from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Any

from arena.token_storage import TokenFileModeWarning, write_owner_token


def token_regenerate(target_path: str = "", *, default_token_file: Path) -> dict[str, Any]:
    """Generate a new token and write it to only this bridge instance's token file."""
    new_tok = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

    if target_path:
        target = Path(target_path).expanduser()
    else:
        env = os.environ.get("ARENA_TOKEN_FILE", "").strip()
        target = Path(env).expanduser() if env else Path(default_token_file)

    mode_warning = ""
    try:
        try:
            write_owner_token(target, new_tok)
        except TokenFileModeWarning as warned:
            # #211 (cubic): the file already holds the new token -- the
            # replace is atomic and completed. Reporting failure here would
            # leave the caller on the old credential in memory while the
            # next restart reads the new one off disk, locking every client
            # out. So this is a success that carries a warning.
            mode_warning = str(warned)
        return {
            "ok": True,
            "token": new_tok,
            "written_to": [str(target)],
            # v4.165.0 (bug #66): the note here used to claim a restart was
            # needed before the previous credential stopped working. That
            # was the opposite of the truth. The route assigns the new value
            # into the live `cfg["token"]`, and `check_auth` compares every
            # request against exactly that, so the old bearer starts
            # returning 401 on the very next request -- the e2e gate
            # asserts precisely this (old_status == 401).
            #
            # The direction of the error is what makes it serious. An
            # operator rotating a LEAKED token was told the leak stayed
            # live until a restart, which invites either a panicked restart
            # or the belief that an attacker still has a window. Both are
            # wrong, and the second is the dangerous one.
            "note": (
                "The new token takes effect immediately: the previous token "
                "is rejected from the next request onward. No restart is "
                "required. Update any client that still holds the old token."
            ),
            "previous_token_revoked": True,
            "restart_required": False,
            **({"warning": mode_warning} if mode_warning else {}),
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to write {target}: {e}"}

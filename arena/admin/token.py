"""Admin token management helpers."""
from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Any

from arena.token_storage import write_owner_token


def token_regenerate(target_path: str = "", *, default_token_file: Path) -> dict[str, Any]:
    """Generate a new token and write it to only this bridge instance's token file."""
    new_tok = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

    if target_path:
        target = Path(target_path).expanduser()
    else:
        env = os.environ.get("ARENA_TOKEN_FILE", "").strip()
        target = Path(env).expanduser() if env else Path(default_token_file)

    try:
        write_owner_token(target, new_tok)
        return {
            "ok": True,
            "token": new_tok,
            "written_to": [str(target)],
            "note": (
                "Existing connections still use the OLD token until the bridge restarts. "
                "Use POST /v1/restart, or click Restart Bridge."
            ),
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to write {target}: {e}"}

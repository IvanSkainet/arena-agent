"""Admin token management helpers."""
from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Any


def token_regenerate(target_path: str = "", *, default_token_file: Path) -> dict[str, Any]:
    """Generate a new token and write it to only this bridge instance's token file."""
    new_tok = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

    if target_path:
        target = Path(target_path).expanduser()
    else:
        env = os.environ.get("ARENA_TOKEN_FILE")
        target = Path(env).expanduser() if env else Path(default_token_file)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_tok, encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except Exception:
            pass
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

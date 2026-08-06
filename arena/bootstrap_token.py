"""Bridge auth token bootstrap helpers."""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from arena.token_storage import write_owner_token


def resolve_token(
    cli_token: str | None,
    *,
    default_token_file: Path,
    token_generator: Callable[[], str],
    log_info: Callable[..., None] | None = None,
) -> tuple[str, Path]:
    """Resolve auth token: CLI arg > env var > token file > auto-generate."""
    env_file = os.environ.get("ARENA_TOKEN_FILE", "").strip()
    token_file = Path(env_file).expanduser() if env_file else default_token_file

    if cli_token:
        return cli_token, token_file

    env_tok = os.environ.get("ARENA_LOCAL_BRIDGE_TOKEN")
    if env_tok:
        return env_tok, token_file

    if token_file.is_symlink():
        raise OSError("refusing to use a symlink token path")

    try:
        existing = token_file.read_text(encoding="utf-8").strip()
        if existing and len(existing) >= 16:
            return existing, token_file
    except FileNotFoundError:
        pass
    except Exception:
        pass

    new_tok = token_generator()
    write_owner_token(token_file, new_tok + "\n")
    if log_info:
        log_info("[ArenaBridge] New token generated and saved to %s", token_file)
    return new_tok, token_file

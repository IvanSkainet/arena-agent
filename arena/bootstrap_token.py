"""Bridge auth token bootstrap helpers."""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from arena.home import code_root, token_path
from arena.token_storage import TokenFileModeWarning, write_owner_token


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

    read_file = token_file
    if not env_file and token_file == code_root() / "token.txt":
        token_file = token_path(for_write=True)

    if cli_token:
        return cli_token, token_file

    env_tok = os.environ.get("ARENA_LOCAL_BRIDGE_TOKEN")
    if env_tok:
        return env_tok, token_file

    if read_file.is_symlink():
        raise OSError("refusing to use a symlink token path")

    try:
        existing = read_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if existing and len(existing) >= 16:
        if token_file != read_file:
            _generate_into(token_file, existing, log_info)
        return existing, token_file

    new_tok = token_generator()
    _generate_into(token_file, new_tok, log_info)
    return new_tok, token_file


def _generate_into(
    token_file: Path,
    new_tok: str,
    log_info: Callable[..., None] | None,
) -> None:
    """Write the first token, tolerating a mode failure after the replace.

    #211 (cubic): `write_owner_token` raises `TokenFileModeWarning` when the
    re-chmod fails *after* `os.replace` has installed the contents, which
    means the generated token IS what the file holds. Aborting the first
    start there left the bridge dead over a permission bit rather than over
    a missing credential, so the warning is logged and startup continues.
    A genuine write failure still propagates.
    """
    try:
        write_owner_token(token_file, new_tok + "\n")
    except TokenFileModeWarning as warned:
        if log_info:
            log_info("[ArenaBridge] %s", warned)
    if log_info:
        log_info("[ArenaBridge] New token generated and saved to %s", token_file)

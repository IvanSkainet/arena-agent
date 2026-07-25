"""Small, pure, stdlib-only helper utilities shared across the bridge.

Re-exported by ``unified_bridge.py`` for backward compatibility.
"""
from __future__ import annotations

import base64
import os
import platform
import secrets
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

# CREATE_NO_WINDOW flag (Windows) — prevents flashing console windows when GUI
# triggers a CIM/powershell/tailscale subprocess. No-op on Linux/macOS.
_NO_WINDOW_FLAG = 0x08000000 if sys.platform == "win32" else 0


def _subprocess_kwargs() -> dict:
    """Common kwargs to silence subprocess child windows on Windows."""
    if sys.platform == "win32":
        return {"creationflags": _NO_WINDOW_FLAG}
    return {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_clean_platform_name() -> str:
    p = platform.platform()
    if sys.platform == "win32":
        try:
            build = int(platform.version().split(".")[-1])
            if build >= 22000:
                p = p.replace("Windows-10", f"Windows-11 (Build {build})")
                p = p.replace("Windows-post2016Server", f"Windows-11 (Build {build})")
        except Exception:
            pass
    return p


def decode_output(data: bytes) -> str:
    if os.name == "nt":
        # v4.80.0: the pre-v4.80.0 implementation used
        # ``errors="replace"`` on every codec, which made the
        # codecs *never* raise -- so the cp1251 / cp866
        # fallbacks were never actually tried (the first
        # iteration succeeded with replacement characters and
        # the function returned the wrong output for any
        # Windows console capture that wasn't already valid
        # UTF-8).
        #
        # The fix: try codecs in *strict* mode (utf-8 first,
        # then cp1251 which is the Windows default ANSI code
        # page for almost all Latin-1 / Cyrillic
        # installations) so the loop has a chance to fall
        # through to the next codec when the current one
        # rejects the bytes. The very last fallback is cp866
        # with ``errors="replace"`` -- a safety net for
        # legacy DOS-encoded captures; the function never
        # raises so callers can always rely on getting a
        # ``str`` back.
        #
        # Note: cp866 is *tried after* cp1251 (not before)
        # because cp866's Cyrillic range is a subset of
        # cp1251's. Putting cp1251 first means a cp1251
        # capture roundtrips correctly; cp866 would also
        # accept those bytes but produce garbled output,
        # which is the bug the previous codec order had.
        for codec in ("utf-8", "cp1251"):
            try:
                return data.decode(codec, errors="strict")
            except Exception:
                continue
        return data.decode("cp866", errors="replace")
    return data.decode("utf-8", "replace")


def b64_token(nbytes: int = 32) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).decode().rstrip("=")


def first_word(cmd: str) -> str:
    try:
        parts = shlex.split(cmd, posix=(os.name != "nt"))
    except Exception:
        parts = cmd.strip().split()
    if not parts:
        return ""
    return Path(parts[0]).name.lower().removesuffix(".exe")


def under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False

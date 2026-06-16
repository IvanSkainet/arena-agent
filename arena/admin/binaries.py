"""Admin helper binary discovery."""
from __future__ import annotations

import os
import platform
import shutil


def which_windows_or_path(binary: str, candidates: list[str]) -> str | None:
    found = shutil.which(binary)
    if not found and platform.system() == "Windows":
        for candidate in candidates:
            if os.path.isfile(candidate):
                found = candidate
                break
    return found

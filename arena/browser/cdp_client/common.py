"""Shared imports/constants for modular CDP browser helpers."""
from __future__ import annotations

import asyncio  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import base64  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import itertools  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import json  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import logging
import os  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import platform  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import shutil  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import socket  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import struct  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import subprocess  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import sys  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import tempfile  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import time  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import traceback  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import urllib.request  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
from pathlib import Path  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
from typing import Any, Callable, Dict, List, Optional  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)

# `aiohttp: Any` (not the inferred `Module | None`) is deliberate: the fallback
# assignment below makes every later `aiohttp.X` read as an attribute on None,
# even on hosts where the package IS installed. Guarded by HAS_AIOHTTP at every
# call site, so the checker gains nothing by tracking the None arm -- it only
# produces noise that hides real findings.
aiohttp: Any
try:
    import aiohttp  # type: ignore[no-redef]
    HAS_AIOHTTP = True
except ImportError:
    aiohttp = None
    HAS_AIOHTTP = False

# `_websockets_mod: Any` (not the inferred `Module | None`): the fallback below
# otherwise makes every later `_websockets_mod.X` read as an attribute on None,
# even where the package is installed. Guarded by HAS_WEBSOCKETS at the call
# sites, so tracking the None arm only produces noise.
_websockets_mod: Any
try:
    import websockets as _websockets_mod  # type: ignore[no-redef]
    HAS_WEBSOCKETS = True
except ImportError:
    _websockets_mod = None
    HAS_WEBSOCKETS = False

logger = logging.getLogger("cdp_browser")
DEFAULT_PORT = 9222
DEFAULT_TIMEOUT = 30
RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY = 1

__all__ = [name for name in globals() if not name.startswith("__")]

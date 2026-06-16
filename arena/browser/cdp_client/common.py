"""Shared imports/constants for modular CDP browser helpers."""
from __future__ import annotations

import asyncio
import base64
import itertools
import json
import logging
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    aiohttp = None
    HAS_AIOHTTP = False

try:
    import websockets as _websockets_mod
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

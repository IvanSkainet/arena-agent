"""Version, filesystem paths and tunable limits for the bridge.

``BRIDGE_DIR`` is the directory that contains ``unified_bridge.py``. Because this
module lives in ``<repo>/arena/constants.py``, the repo root is this file's
grandparent (``parent.parent``) — NOT ``parent`` (which would be the ``arena/``
package directory).

Re-exported by ``unified_bridge.py`` for backward compatibility.
"""
from __future__ import annotations

from pathlib import Path

VERSION = "4.60.15"
AUDIT_CMD_LIMIT = 4000

# Directory containing unified_bridge.py (the install/repo root).
BRIDGE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BRIDGE_DIR
TOKEN_FILE = APP_DIR / "token.txt"
AUDIT = APP_DIR / "audit.jsonl"

MAX_BODY = 1024 * 1024
DEFAULT_MAX_OUTPUT = 2 * 1024 * 1024
DEFAULT_MAX_CONCURRENT = 3

















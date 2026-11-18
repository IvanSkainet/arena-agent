"""Version, filesystem paths and tunable limits for the bridge.

``BRIDGE_DIR`` is the directory that contains ``unified_bridge.py``. Because this
module lives in ``/arena/constants.py``, the repo root is this file's
grandparent (``parent.parent``) — NOT ``parent`` (which would be the ``arena/``
package directory).

Re-exported by ``unified_bridge.py`` for backward compatibility.
"""
from __future__ import annotations

from pathlib import Path

from arena.home import agent_home, token_path

VERSION = "4.170.0"
AUDIT_CMD_LIMIT = 4000

# Directory containing unified_bridge.py (the install/repo root).
BRIDGE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BRIDGE_DIR
# State, not code. These two used to live next to unified_bridge.py, which meant a
# default run dropped a token and an audit log into the checkout (and into
# site-packages on a pip install) -- the same mistake `arena.paths` made with the
# queue and mission directories (#B-019, #B-006). APP_DIR stays as the *code* root.
TOKEN_FILE = token_path()
AUDIT = agent_home() / "audit.jsonl"

MAX_BODY = 1024 * 1024
DEFAULT_MAX_OUTPUT = 2 * 1024 * 1024
DEFAULT_MAX_CONCURRENT = 3

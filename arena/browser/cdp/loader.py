"""Lazy cdp_browser module loader."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from arena.constants import BRIDGE_DIR

log = logging.getLogger("arena-bridge")
_cdp_module = None


def _get_cdp_module():
    """Lazily import cdp_browser from scripts/ directory."""
    global _cdp_module
    if _cdp_module is not None:
        return _cdp_module

    search_paths = [BRIDGE_DIR / "scripts"]
    for scripts_dir in search_paths:
        cdp_path = scripts_dir / "cdp_browser.py"
        if cdp_path.exists():
            sys.path.insert(0, str(scripts_dir))
            break

    try:
        import cdp_browser
        _cdp_module = cdp_browser

        bridge_logger = logging.getLogger("arena-bridge")
        cdp_logger = logging.getLogger("cdp_browser")
        cdp_logger.setLevel(logging.DEBUG)
        cdp_logger.handlers.clear()
        for handler in bridge_logger.handlers:
            cdp_logger.addHandler(handler)
        cdp_logger.propagate = False
        log.info("[CDP] Configured cdp_browser logger with %d handler(s)", len(bridge_logger.handlers))

        return _cdp_module
    except ImportError:
        return None

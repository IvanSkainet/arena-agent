#!/usr/bin/env python3
"""Thin CLI wrapper around ``arena.security.alerts``.

The gate itself -- networking, alert processing, severity ranking and
output -- lives in ``arena/security/alerts.py``. This file only resolves
the repository root onto ``sys.path``, hands the argv over and returns
the exit code, which is the boundary `scripts/` entrypoints are supposed
to keep (#190).

Kept as a script because CI, `scripts/preflight.py` and
`security-scan.yml` all invoke it by path:

    python scripts/security_alerts_check.py --max-severity medium
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arena.security.alerts import main  # noqa: E402 -- needs the path line above

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

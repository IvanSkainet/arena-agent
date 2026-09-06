"""Bounds on what a mission request may ask for.

One constant so far, in a module of its own because three packages need it
-- `resources`, `wiring` and the schedule runtime -- and putting it in any
one of them made the other two import it in a cycle (#270).
"""
from __future__ import annotations

__all__ = ["MAX_MISSION_TIMEOUT_S"]

# A mission timeout ends up as `subprocess.run(..., timeout=...)`, and
# selectors.poll refuses anything past its own limits: `{"timeout":
# 1578655390615}` came back as `OverflowError: timestamp too large to convert
# to C PyTime_t`, a 500 for a number that is valid JSON. A day is far past
# any real mission and comfortably inside what the C layer accepts.
MAX_MISSION_TIMEOUT_S = 86_400

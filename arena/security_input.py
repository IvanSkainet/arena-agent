"""Desktop input-injection command detection."""
from __future__ import annotations

import re

_INPUT_INJECTION_PATTERNS = [
    r"\bydotool\b",
    r"\bwtype\b",
    r"\bdotoolc?\b",
    r"\bxdotool\b\s+[^|;&]*\b(key|keydown|keyup|type|click|mouse(move|down|up)?|windowactivate|windowfocus)\b",
    r"\bwlrctl\b",
    r"\bydotoold\b",
]


def _is_input_injection_cmd(cmd: str) -> str | None:
    """Return the matched pattern if cmd would inject desktop input, else None."""
    low = cmd.lower()
    for pat in _INPUT_INJECTION_PATTERNS:
        if re.search(pat, low, flags=re.I | re.S):
            return pat
    return None

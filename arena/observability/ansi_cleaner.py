"""Sanitizer for ANSI escape sequences to prevent terminal injection in log streams."""
import re

_ANSI_ESCAPE_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_ansi(text: str) -> str:
    """Remove all ANSI escape codes from the input string."""
    if not text:
        return ""
    return _ANSI_ESCAPE_RE.sub('', text)

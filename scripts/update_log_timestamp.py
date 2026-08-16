"""Strict timestamp contract for Windows auto-update mover logs."""
from __future__ import annotations

import re
from datetime import datetime

# The mover writes `%DATE% %TIME%`, whose shape follows the Windows locale.
# Keep accepted spellings explicit: broad "some digits and punctuation" parsing
# would turn corrupt diagnostics into apparently healthy phases.
LINE_RE = re.compile(
    r"^\[(?P<date>\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})"
    r"\s+(?P<time>\d{1,2}:\d{2}:\d{2}[.,]\d{1,6})\]\s+(?P<rest>.*)$"
)

_FORMATS = {
    ("-", "."): "%Y-%m-%d %H:%M:%S.%f",
    (".", ","): "%d.%m.%Y %H:%M:%S,%f",
}


def parse_timestamp(date_text: str, time_text: str) -> datetime:
    """Parse one of the two mover timestamp shapes we have real evidence for."""
    for (date_separator, time_separator), fmt in _FORMATS.items():
        if date_separator in date_text and time_separator in time_text:
            return datetime.strptime(f"{date_text} {time_text}", fmt)
    raise ValueError(f"unsupported mover timestamp shape: {date_text} {time_text}")


__all__ = ["LINE_RE", "parse_timestamp"]

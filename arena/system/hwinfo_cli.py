"""CLI for scripts/hwinfo.py."""
from __future__ import annotations

import json
import sys

from arena.system.hwinfo_collect import collect_full, collect_standard


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--full":
        print(json.dumps(collect_full(), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(collect_standard(), indent=2, ensure_ascii=False))

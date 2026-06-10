import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _arena_helper as helper  # noqa: E402
from arena.constants import VERSION  # noqa: E402


def test_helper_reads_canonical_version():
    assert helper.get_version() == VERSION
    assert helper.get_version() != "unknown"

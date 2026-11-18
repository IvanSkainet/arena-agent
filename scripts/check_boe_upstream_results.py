#!/usr/bin/env python3
"""Fail closed if a filtered upstream contract silently stops selecting tests."""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REQUIRED_TESTS = frozenset({
    "Helper_CompleteBoeTurnWritesCorrelatedTerminalSignal",
    "Helper_CompleteBoeValidationRepairAllowsRepairReadyAfterAcceptedTurnCompletion",
    "DaemonAutomaticDispatch_DoesNotSendBootstrapAsSeparateGmRequest",
})


def check_results(path: Path) -> None:
    root = ET.parse(path).getroot()
    results = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "UnitTestResult"]
    names: set[str] = set()
    for node in results:
        name = node.get("testName", "").rsplit(".", 1)[-1]
        if name not in REQUIRED_TESTS or name in names or node.get("outcome") != "Passed":
            raise ValueError(f"unexpected, duplicated, or non-passing upstream result: {name}")
        names.add(name)
    missing = REQUIRED_TESTS - names
    if missing:
        raise ValueError(f"missing upstream contract results: {', '.join(sorted(missing))}")


if __name__ == "__main__":
    check_results(Path(sys.argv[1]))
    print("all three upstream contracts selected and passed")

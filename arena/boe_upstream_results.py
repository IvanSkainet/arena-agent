"""Strict selection and safe XML parsing for optional upstream contracts."""
from __future__ import annotations

from pathlib import Path
from xml.etree import (
    ElementTree,  # nosec B405 -- DTD-rejecting builder below  # nosemgrep: use-defused-xml -- _NoDtdBuilder rejects DTDs at parser level, including UTF-16; adversarial fixtures verify entity rejection
)

REQUIRED_TESTS = frozenset({
    "Helper_CompleteBoeTurnWritesCorrelatedTerminalSignal",
    "Helper_CompleteBoeValidationRepairAllowsRepairReadyAfterAcceptedTurnCompletion",
    "DaemonAutomaticDispatch_DoesNotSendBootstrapAsSeparateGmRequest",
})


class _NoDtdBuilder(ElementTree.TreeBuilder):
    """TRX needs elements and attributes, never document type declarations."""

    def doctype(self, _name, _pubid, _system):
        raise ValueError("DTD declarations are forbidden in upstream reports")


def check_results(path: Path) -> None:
    # Reject DTDs at parser level, including UTF-16 documents: byte substring
    # checks miss encodings. No entity declaration can reach the tree builder.
    parser = ElementTree.XMLParser(target=_NoDtdBuilder())  # nosec B314 -- _NoDtdBuilder rejects DTDs for every encoding
    root = ElementTree.parse(path, parser=parser).getroot()  # nosec B314 -- DTD rejected above  # nosemgrep: use-defused-xml-parse -- parser uses _NoDtdBuilder, which refuses every document type before entity expansion
    results = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "UnitTestResult"]
    names: set[str] = set()
    for node in results:
        name = node.get("testName", "").rsplit(".", 1)[-1]
        _validate_result(name, names, node.get("outcome"))
        names.add(name)
    missing = REQUIRED_TESTS - names
    if missing:
        raise ValueError(f"missing upstream contract results: {', '.join(sorted(missing))}")


def _validate_result(name: str, names: set[str], outcome: str | None) -> None:
    if name not in REQUIRED_TESTS:
        raise ValueError(f"unexpected upstream result: {name}")
    if name in names:
        raise ValueError(f"duplicated upstream result: {name}")
    if outcome != "Passed":
        raise ValueError(f"non-passing upstream result: {name}")


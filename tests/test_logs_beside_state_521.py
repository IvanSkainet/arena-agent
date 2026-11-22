"""#521: the request log and the bridge log are state, kept beside the audit log and not beside the code."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

import unified_bridge as ub
from arena import constants
from arena.wiring.base_runtime import build_base_runtime

REPO = Path(__file__).resolve().parents[1]


def test_both_logs_are_kept_beside_the_audit_log():
    """One rule for all three: an install that keeps its state beside the code keeps its logs there too."""
    assert {constants.REQUEST_LOG.parent, constants.BRIDGE_LOG.parent} == {constants.AUDIT.parent}


@pytest.mark.parametrize("name", ["REQUEST_LOG", "BRIDGE_LOG"])
def test_under_the_suite_neither_log_is_in_the_checkout(name):
    """Every worker has its own agent home; a log in the repository would be shared by all of them."""
    assert REPO not in getattr(constants, name).resolve().parents


def test_a_served_request_is_written_to_the_declared_log():
    """The bridge's own writer, not a stand-in: this is what appended to the checkout before."""
    beside_the_code = REPO / "requests.jsonl"
    before = beside_the_code.stat().st_size if beside_the_code.exists() else None
    ub._log_request_response("GET", "/v1/probe-521", 200, 0.001, "probe-521")
    last = constants.REQUEST_LOG.read_text(encoding="utf-8").splitlines()[-1]
    assert json.loads(last)["req_id"] == "probe-521"
    assert (beside_the_code.stat().st_size if beside_the_code.exists() else None) == before


def test_the_reader_and_the_writer_share_one_file():
    """The request-log endpoint reads what the middleware wrote."""
    assert ub._REQ_LOG_FILE == constants.REQUEST_LOG


def test_the_bridge_log_is_opened_where_it_is_declared(tmp_path):
    """And its directory is the one created for it: a fresh agent home does not exist yet."""
    opened = {}
    declared = tmp_path / "state" / "bridge.log"
    runtime = build_base_runtime({
        "BRIDGE_DIR": tmp_path,
        "BRIDGE_LOG": declared,
        "_setup_logging_runtime": lambda **kwargs: opened.update(kwargs) or logging.getLogger("probe-521"),
    })
    for name in ("_EXECUTOR", "_SLOW_EXECUTOR"):
        runtime[name].shutdown()
    assert opened == {"app_dir": declared.parent, "log_file": declared}
    assert runtime["LOG_FILE"] == declared

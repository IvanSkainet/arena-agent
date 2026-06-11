"""Request log helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.observability.request_log import log_request_response, read_request_log  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_request_log_write_and_filter(tmp_path):
    log_file = tmp_path / "requests.jsonl"
    log_request_response(log_file=log_file, app_dir=tmp_path, utc_now_fn=lambda: "now", method="GET", path="/v1/test", status=200, duration=0.123, req_id="abc")
    log_request_response(log_file=log_file, app_dir=tmp_path, utc_now_fn=lambda: "now", method="POST", path="/v1/other", status=500, duration=0.1, req_id="def", error="boom")
    all_entries = read_request_log(log_file, lines_count=10)
    assert len(all_entries) == 2
    filtered = read_request_log(log_file, method_filter="GET")
    assert len(filtered) == 1
    assert filtered[0]["path"] == "/v1/test"
    filtered_status = read_request_log(log_file, status_filter="500")
    assert filtered_status[0]["error"] == "boom"


def test_unified_bridge_request_log_wrapper(tmp_path):
    # Ensure the wrapper exists and module imports are wired.
    assert callable(ub._log_request_response)
    assert ub.request_log_lock is not None

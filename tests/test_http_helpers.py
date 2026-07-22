"""HTTP helper module tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.web_utils import CORS_HEADERS, _cors_json_response, cors_json_response  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_cors_json_response_headers():
    resp = cors_json_response({"ok": True}, extra_headers={"X-Test": "yes"})
    assert resp.status == 200
    assert resp.headers["Access-Control-Allow-Origin"] == "*"
    assert resp.headers["X-Test"] == "yes"


def test_unified_bridge_reexports_cors_helper():
    assert ub._cors_json_response is _cors_json_response
    assert "Access-Control-Allow-Methods" in CORS_HEADERS

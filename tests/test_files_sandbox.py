"""File sandbox helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.files.sandbox import validate_download_target, validate_upload_target  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_validate_upload_target_blocks_traversal_and_bridge(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    bridge = home / "bridge.py"; bridge.write_text("x")
    path, err, status = validate_upload_target("../x", root=home, home=home, bridge_py=bridge)
    assert err == "path traversal not allowed" and status == 400
    path, err, status = validate_upload_target(str(bridge), root=home, home=home, bridge_py=bridge)
    assert err == "cannot overwrite the bridge itself" and status == 403


def test_validate_download_target(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    f = home / "file.txt"; f.write_text("hello")
    path, err, status = validate_download_target("file.txt", root=home, home=home)
    assert err is None and path == f
    path, err, status = validate_download_target("missing.txt", root=home, home=home)
    assert err == "file not found" and status == 404


def test_unified_file_handlers_registered():
    app = ub.make_app({"token": "test", "profile": "owner-shell", "root": "/tmp", "active_exec": 0, "max_concurrent": 3, "audit": "audit"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("POST", "/v1/upload") in paths
    assert ("GET", "/v1/download") in paths

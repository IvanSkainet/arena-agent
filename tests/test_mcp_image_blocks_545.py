"""#545: a screenshot taken over MCP reaches the model as a picture, not as base64 text."""
from __future__ import annotations

import base64
import io
import json
import struct
import urllib.error
import zlib

import pytest

import arena.mcp.tool_desktop_app as app
import arena.mcp.tool_desktop_screenshot as shot_tool
from arena.mcp.image_result import sniff_image
from arena.mcp.tool_registry import MCP_TOOLS

WINDOW = {"id": "w-1", "internal_id": "w-1", "title": "Notes", "pid": 7,
          "geometry": {"x": 100, "y": 50, "width": 800, "height": 600}}
DISPLAYS_PAYLOAD = {"ok": True, "active_output": "DP-2", "displays": [
    {"name": "DP-1", "primary": True, "geometry": {"x": 0, "y": 0, "width": 1920, "height": 1080}},
    {"name": "DP-2", "primary": False, "geometry": {"x": 1920, "y": 0, "width": 2560, "height": 1440}},
]}


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def _png_b64(width: int, height: int) -> str:
    """A real, decodable grey PNG of the given size."""
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    rows = (b"\x00" + b"\x80" * width) * height
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(rows)) + _chunk(b"IEND", b"")
    return base64.b64encode(png).decode("ascii")


def _bmp_b64(width: int, height: int) -> str:
    header = b"BM" + struct.pack("<IHHI", 54, 0, 0, 54) + struct.pack("<Iii", 40, width, -height) + b"\x00" * 28
    return base64.b64encode(header).decode("ascii")


def _shot(data: str, **extra) -> dict:
    return {"ok": True, "format": "base64", "encoding": "png", "data": data, "size_bytes": 1, **extra}


class _Bridge:
    """Stand-in for the bridge REST routes the two tools read."""

    def __init__(self, picture: dict, windows: list[dict]):
        self.picture = picture
        self.windows = windows
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, _ctx, path, params=None):
        self.calls.append((path, params))
        if path == "/v1/desktop/windows":
            return {"ok": True, "count": len(self.windows), "all_count": len(self.windows), "windows": self.windows}
        if path == "/v1/desktop/displays":
            return DISPLAYS_PAYLOAD
        return dict(self.picture)

    def post(self, _ctx, path, _payload):
        self.calls.append((path, None))
        return {"ok": True}

    def screenshot_params(self) -> dict:
        return next(params for path, params in self.calls if path == "/v1/desktop/screenshot")


@pytest.fixture(name="bridge")
def _bridge(monkeypatch):
    def install(picture: dict, windows: tuple[dict, ...] = (WINDOW,)) -> _Bridge:
        fake = _Bridge(picture, list(windows))
        monkeypatch.setattr(app, "_bridge_get", fake.get)
        monkeypatch.setattr(app, "_bridge_call", fake.post)
        monkeypatch.setattr(shot_tool, "_bridge_get", fake.get)
        return fake
    return install


def _window_shot(args: dict) -> dict:
    return app.handle_desktop_app_tool("desktop_app.screenshot_window", {"title": "Notes", **args}, ctx=object())


def _screen_shot(args: dict) -> dict:
    return shot_tool.handle_desktop_screenshot_tool("desktop.screenshot", args, ctx=object())


def _words(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def test_window_screenshot_arrives_as_an_image_block(bridge):
    data = _png_b64(400, 300)
    bridge(_shot(data))

    result = _window_shot({"max_width": 400})

    assert [part["type"] for part in result["content"]] == ["text", "image"]
    assert result["content"][1] == {"type": "image", "data": data, "mimeType": "image/png"}
    assert not result.get("isError")
    # The picture is decodable as delivered, not merely labelled as one.
    assert sniff_image(base64.b64decode(result["content"][1]["data"])) == {"mimeType": "image/png", "width": 400, "height": 300}


def test_the_words_describe_the_picture_without_repeating_it(bridge):
    data = _png_b64(400, 300)
    bridge(_shot(data))

    result = _window_shot({"max_width": 400})
    words = _words(result)

    assert data not in result["content"][0]["text"]
    assert "data" not in words
    assert words["target"]["title"] == "Notes"
    assert words["image"] == {"mimeType": "image/png", "width": 400, "height": 300, "delivered_as": "image content block"}
    assert words["image_to_desktop"]["available"] is True
    assert words["image_to_desktop"]["origin"] == {"x": 100, "y": 50}
    assert words["image_to_desktop"]["scale"] == 2.0


def test_a_clipped_capture_does_not_claim_a_coordinate_mapping(bridge):
    # The window is 800x600, but the capture was cut at a screen edge to 800x450.
    bridge(_shot(_png_b64(400, 225)))

    mapping = _words(_window_shot({"max_width": 400}))["image_to_desktop"]

    assert mapping["available"] is False
    assert "origin" not in mapping
    assert "scale" not in mapping


def test_base64_format_keeps_the_json_only_answer(bridge):
    data = _png_b64(400, 300)
    bridge(_shot(data))

    result = _window_shot({"format": "base64"})

    assert [part["type"] for part in result["content"]] == ["text"]
    assert _words(result)["data"] == data


def test_a_window_that_is_not_found_is_an_error_without_a_picture(bridge):
    bridge(_shot(_png_b64(4, 4)), windows=())

    result = _window_shot({})

    assert result["isError"] is True
    assert [part["type"] for part in result["content"]] == ["text"]
    assert _words(result)["error"] == "window_not_found"


def test_an_uncompressed_bmp_is_refused_instead_of_delivered(bridge):
    bridge(_shot(_bmp_b64(2560, 1440), size_bytes=19_661_037))

    result = _window_shot({})

    assert result["isError"] is True
    assert [part["type"] for part in result["content"]] == ["text"]
    assert _words(result)["error"] == "screenshot_is_uncompressed_bmp"
    assert "Pillow" in _words(result)["detail"]


def test_bytes_that_are_no_picture_are_refused(bridge):
    bridge(_shot(base64.b64encode(b"not a picture at all").decode("ascii")))

    result = _window_shot({})

    assert result["isError"] is True
    assert _words(result)["error"] == "screenshot_not_an_image"


def test_window_screenshot_schema_declares_every_argument_it_reads():
    schema = next(t for t in MCP_TOOLS if t["name"] == "desktop_app.screenshot_window")["inputSchema"]

    assert schema["additionalProperties"] is False
    assert {"focus", "require_focus", "format", "max_width", "scale"} <= set(schema["properties"])
    assert schema["properties"]["format"]["enum"] == ["image", "base64"]
    assert schema["properties"]["format"]["default"] == "image"


def test_desktop_screenshot_is_declared():
    schema = next(t for t in MCP_TOOLS if t["name"] == "desktop.screenshot")["inputSchema"]

    assert set(schema["properties"]) == {"display", "region", "max_width", "scale"}
    assert schema["properties"]["region"]["required"] == ["x", "y", "width", "height"]


def test_desktop_screenshot_without_arguments_takes_the_active_display(bridge):
    geometry = DISPLAYS_PAYLOAD["displays"][1]["geometry"]
    fake = bridge(_shot(_png_b64(1280, 720), display="DP-2", crop_region=geometry))

    result = _screen_shot({})

    assert fake.screenshot_params() == {"display": "DP-2", "format": "base64", "max_width": 1280}
    assert [part["type"] for part in result["content"]] == ["text", "image"]
    words = _words(result)
    assert words["display"] == "DP-2"
    assert words["image_to_desktop"] == {
        "available": True, "origin": {"x": 1920, "y": 0}, "scale": 2.0,
        "formula": "desktop_x = origin.x + image_x * scale; desktop_y = origin.y + image_y * scale",
    }


def test_desktop_screenshot_of_a_region_asks_for_exactly_that_region(bridge):
    region = {"x": 10, "y": 20, "width": 640, "height": 480}
    fake = bridge(_shot(_png_b64(640, 480), crop_region=region))

    result = _screen_shot({"region": region, "max_width": 640})

    assert fake.screenshot_params() == {
        "region_x": 10, "region_y": 20, "region_width": 640, "region_height": 480, "format": "base64", "max_width": 640,
    }
    assert [path for path, _ in fake.calls] == ["/v1/desktop/screenshot"]
    assert _words(result)["image_to_desktop"]["scale"] == 1.0


def test_an_explicit_scale_replaces_the_default_width(bridge):
    fake = bridge(_shot(_png_b64(960, 540), display="DP-1", crop_region=DISPLAYS_PAYLOAD["displays"][0]["geometry"]))

    _screen_shot({"display": "DP-1", "scale": 0.5})

    assert fake.screenshot_params() == {"display": "DP-1", "format": "base64", "scale": 0.5}


@pytest.mark.parametrize("args, fragment", [
    ({"display": "DP-1", "region": {"x": 0, "y": 0, "width": 10, "height": 10}}, "not both"),
    ({"region": {"x": 0, "y": 0, "width": 0, "height": 10}}, "width > 0"),
    ({"region": {"x": 0, "y": 0, "width": 10}}, "width > 0"),
    ({"region": "everything"}, "width > 0"),
])
def test_desktop_screenshot_refuses_a_target_it_cannot_capture(bridge, args, fragment):
    fake = bridge(_shot(_png_b64(4, 4)))

    result = _screen_shot(args)

    assert result["isError"] is True
    assert fragment in _words(result)["error"]
    assert fake.calls == []


def test_a_bridge_refusal_is_passed_on_in_its_own_words(monkeypatch):
    body = json.dumps({"ok": False, "error": "unknown display 'HDMI-9'", "available": ["DP-1"]}).encode("utf-8")

    def refuse(_ctx, path, _params=None):
        raise urllib.error.HTTPError(f"http://127.0.0.1{path}", 404, "Not Found", None, io.BytesIO(body))

    monkeypatch.setattr(shot_tool, "_bridge_get", refuse)

    result = _screen_shot({"display": "HDMI-9"})

    assert result["isError"] is True
    assert _words(result) == {"ok": False, "error": "unknown display 'HDMI-9'", "available": ["DP-1"]}


def test_a_refusal_that_is_not_json_still_says_what_happened(monkeypatch):
    def refuse(_ctx, path, _params=None):
        raise urllib.error.HTTPError(f"http://127.0.0.1{path}", 502, "Bad Gateway", None, io.BytesIO(b"<html>upstream</html>"))

    monkeypatch.setattr(shot_tool, "_bridge_get", refuse)

    words = _words(_screen_shot({"display": "DP-1"}))

    assert words["ok"] is False
    assert "502" in words["error"]
    assert "upstream" in words["detail"]


def test_other_tools_are_not_claimed_by_the_screenshot_handler():
    assert shot_tool.handle_desktop_screenshot_tool("desktop.displays", {}, ctx=object()) is None

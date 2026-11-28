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
    """A bridge answer; by default the bridge says it captured exactly the test window."""
    return {"ok": True, "format": "base64", "encoding": "png", "data": data, "size_bytes": 1,
            "captured_region": WINDOW["geometry"], **extra}


class _Bridge:
    """Stand-in for the bridge REST routes the two tools read."""

    def __init__(self, picture: dict, windows: list[dict]):
        self.picture = picture
        self.windows = windows
        self.displays = DISPLAYS_PAYLOAD
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, _ctx, path, params=None):
        self.calls.append((path, params))
        if path == "/v1/desktop/windows":
            return {"ok": True, "count": len(self.windows), "all_count": len(self.windows), "windows": self.windows}
        if path == "/v1/desktop/displays":
            return self.displays
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
    assert "format" not in words
    assert words["target"]["title"] == "Notes"
    assert words["image"] == {"mimeType": "image/png", "width": 400, "height": 300, "delivered_as": "image content block"}
    assert words["image_to_desktop"]["available"] is True
    assert words["image_to_desktop"]["origin"] == {"x": 100, "y": 50}
    assert words["image_to_desktop"]["scale"] == 2.0


def test_a_clipped_capture_is_mapped_from_the_area_that_was_kept(bridge):
    # The window is 800x600 at (100, 50); the screen ended 150 pixels early, so 800x450 was kept.
    bridge(_shot(_png_b64(400, 225), captured_region={"x": 100, "y": 50, "width": 800, "height": 450}))

    mapping = _words(_window_shot({"max_width": 400}))["image_to_desktop"]

    assert mapping["available"] is True
    assert mapping["origin"] == {"x": 100, "y": 50}
    assert mapping["scale"] == 2.0


def test_a_shifted_capture_is_mapped_from_where_it_really_starts(bridge):
    # Asked for a window hanging off the left and top edges; the same-sized picture starts at (0, 0).
    bridge(_shot(_png_b64(400, 300), captured_region={"x": 0, "y": 0, "width": 800, "height": 600}),
           windows=({**WINDOW, "geometry": {"x": -800, "y": -600, "width": 800, "height": 600}},))

    words = _words(_window_shot({"max_width": 400}))

    assert words["geometry"]["x"] == -800
    assert words["image_to_desktop"]["origin"] == {"x": 0, "y": 0}
    assert words["image_to_desktop"]["scale"] == 2.0


@pytest.mark.parametrize("captured", [
    None,
    {"x": 0, "y": 0, "width": 800, "height": 300},
    {"x": 0, "y": 0, "width": 0, "height": 0},
    "everything",
])
def test_no_mapping_is_claimed_without_a_captured_area_that_fits_the_picture(bridge, captured):
    bridge(_shot(_png_b64(400, 300), captured_region=captured))

    mapping = _words(_window_shot({"max_width": 400}))["image_to_desktop"]

    assert mapping["available"] is False
    assert "origin" not in mapping
    assert "scale" not in mapping


def test_a_capture_of_an_unknown_region_says_the_mapping_is_unknown(bridge):
    # A host that cannot list its displays captures the whole desktop and reports no region.
    fake = bridge(_shot(_png_b64(1280, 720), crop_region=None, captured_region=None, display=None))
    fake.displays = {"ok": True, "displays": []}

    words = _words(_screen_shot({}))

    assert fake.screenshot_params() == {"format": "base64", "max_width": 1280}
    assert words["image"]["width"] == 1280
    assert words["image_to_desktop"]["available"] is False
    assert "origin" not in words["image_to_desktop"]


def test_base64_format_keeps_the_json_only_answer(bridge):
    data = _png_b64(400, 300)
    bridge(_shot(data))

    result = _window_shot({"format": "base64"})

    assert [part["type"] for part in result["content"]] == ["text"]
    assert _words(result)["data"] == data


@pytest.mark.parametrize("args", [{}, {"format": "base64"}, {"format": "gif"}])
def test_a_window_that_is_not_found_is_an_error_without_a_picture(bridge, args):
    bridge(_shot(_png_b64(4, 4)), windows=())

    result = _window_shot(args)

    assert result["isError"] is True
    assert [part["type"] for part in result["content"]] == ["text"]
    assert _words(result)["error"] == "window_not_found"


def test_an_unsupported_format_is_an_error_in_words(bridge):
    bridge(_shot(_png_b64(4, 4)))

    result = _window_shot({"format": "gif"})

    assert result["isError"] is True
    assert [part["type"] for part in result["content"]] == ["text"]
    assert "format='image'" in _words(result)["error"]


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
    fake = bridge(_shot(_png_b64(1280, 720), display="DP-2", crop_region=geometry, captured_region=geometry))

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
    fake = bridge(_shot(_png_b64(640, 480), crop_region=region, captured_region=region))

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
    # The route's answer, word for word; the status and the route are added because it did not give them (#620).
    assert _words(result) == {"ok": False, "error": "unknown display 'HDMI-9'", "available": ["DP-1"],
                              "status": 404, "route": "/v1/desktop/screenshot"}


def test_a_refusal_that_is_not_json_still_says_what_happened(monkeypatch):
    def refuse(_ctx, path, _params=None):
        raise urllib.error.HTTPError(f"http://127.0.0.1{path}", 502, "Bad Gateway", None, io.BytesIO(b"<html>upstream</html>"))

    monkeypatch.setattr(shot_tool, "_bridge_get", refuse)

    words = _words(_screen_shot({"display": "DP-1"}))

    assert words["ok"] is False
    assert "502" in words["error"]
    assert "upstream" in words["detail"]


def test_the_active_display_falls_back_to_primary_then_to_the_first_name(bridge):
    fake = bridge(_shot(_png_b64(4, 4)))
    fake.displays = {"ok": True, "active_output": "GONE", "displays": [{"name": "B"}, {"name": "A", "primary": True}, "junk"]}
    _screen_shot({})
    assert fake.screenshot_params()["display"] == "A"

    fake.calls.clear()
    fake.displays = {"ok": True, "displays": [{"name": "B"}, {"name": "A"}, {"name": ""}]}
    _screen_shot({})
    assert fake.screenshot_params()["display"] == "A"


def test_the_dispatcher_reaches_desktop_screenshot(bridge):
    bridge(_shot(_png_b64(1280, 720), display="DP-2"))

    result = app.handle_desktop_app_tool("desktop.screenshot", {}, ctx=object())

    assert [part["type"] for part in result["content"]] == ["text", "image"]
    assert app.handle_desktop_app_tool("desktop.displays", {}, ctx=object()) is None


class _Picture:
    """The two things the crop needs from a Pillow image."""

    def __init__(self, size):
        self.size = size
        self.cropped_to = None

    def crop(self, box):
        self.cropped_to = box
        return _Picture((box[2] - box[0], box[3] - box[1]))


@pytest.mark.parametrize("region, kept", [
    ({"x": 100, "y": 50, "width": 800, "height": 600}, {"x": 100, "y": 50, "width": 800, "height": 600}),
    # Hanging over the right and bottom edges: the picture is smaller than the region.
    ({"x": 1500, "y": 900, "width": 800, "height": 600}, {"x": 1500, "y": 900, "width": 420, "height": 180}),
    # Hanging over the left and top edges: same size, but it starts at the screen corner.
    ({"x": -800, "y": -600, "width": 800, "height": 600}, {"x": 0, "y": 0, "width": 800, "height": 600}),
    # Larger than the screen in the same proportions: only the screen is in the picture.
    ({"x": 0, "y": 0, "width": 3840, "height": 2160}, {"x": 0, "y": 0, "width": 1920, "height": 1080}),
])
def test_the_crop_reports_the_area_it_kept(region, kept):
    from arena.desktop.screenshot_crop import crop_kept

    picture = _Picture((1920, 1080))
    cropped, reported = crop_kept(picture, region)

    assert reported == kept
    assert cropped.size == (kept["width"], kept["height"])
    assert picture.cropped_to == (kept["x"], kept["y"], kept["x"] + kept["width"], kept["y"] + kept["height"])


def test_no_region_means_no_crop_and_no_claim():
    from arena.desktop.screenshot_crop import crop_kept

    picture = _Picture((1920, 1080))

    assert crop_kept(picture, None) == (picture, None)
    assert picture.cropped_to is None


def _finalize(already_cropped: bool) -> dict:
    from arena.desktop.screenshot import _finalize_screenshot

    return _finalize_screenshot(
        b"raw-bytes", tool="user32", fmt="base64", scale=None, max_width=None, quality=80,
        region_x=-8, region_y=-8, region_width=1936, region_height=1056, audit_fn=None, already_cropped=already_cropped,
    )


def test_a_backend_that_cropped_on_capture_reports_the_region_it_was_given():
    shot = _finalize(already_cropped=True)

    assert shot["captured_region"] == {"x": -8, "y": -8, "width": 1936, "height": 1056}
    assert shot["bytes"] == b"raw-bytes"


def test_a_crop_that_could_not_be_done_claims_no_captured_area():
    # These bytes are no picture, so the transform fails and the raw capture is returned uncropped.
    shot = _finalize(already_cropped=False)

    assert shot["ok"] is True
    assert shot["bytes"] == b"raw-bytes"
    assert shot["crop_region"] == {"x": -8, "y": -8, "width": 1936, "height": 1056}
    assert shot["captured_region"] is None


def test_the_rest_answer_carries_both_the_asked_and_the_captured_region():
    from arena.desktop.screenshot_handler import _base64_body

    asked = {"x": -8, "y": -8, "width": 100, "height": 100}
    kept = {"x": 0, "y": 0, "width": 100, "height": 100}
    body = _base64_body({"bytes": b"abc", "encoding": "png", "tool": "grim", "crop_region": asked, "captured_region": kept}, "")

    assert body["crop_region"] == asked
    assert body["captured_region"] == kept
    assert body["data"] == "YWJj"
    assert body["display"] is None


def test_other_tools_are_not_claimed_by_the_screenshot_handler():
    assert shot_tool.handle_desktop_screenshot_tool("desktop.displays", {}, ctx=object()) is None

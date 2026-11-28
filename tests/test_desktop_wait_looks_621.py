"""#621: what one look is -- a window listed, two captures compared, words read off the screen."""
# Every producer is a function the test writes; no window is listed, no screen captured.
from __future__ import annotations

import asyncio
import struct
import zlib

import pytest

from arena.desktop.frame_compare import Frame, compared_as, read_frame
from arena.desktop.wait import CannotLook, Look
from arena.desktop.wait_looks import screen_look, text_look, window_look

GAME = {"id": "7", "title": "Abyssal Ascent - Minecraft", "class": "GLFW30", "geometry": {"width": 800, "height": 600}}
NOTES = {"id": "8", "title": "Notes", "class": "Editor", "geometry": {"width": 400, "height": 300}}
GAME_SMALL = {"id": "9", "title": "minecraft launcher", "class": "Launcher", "geometry": {"width": 10, "height": 10}}


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(pixels: bytes, *, size=(2, 2), stamp: bytes = b"", packed_as=(6, 1)) -> bytes:
    """A PNG file around `pixels`: an optional time stamp; `packed_as` is (compression level, number of chunks)."""
    level, pieces = packed_as
    header = struct.pack(">IIBBBBB", size[0], size[1], 8, 0, 0, 0, 0)
    packed = zlib.compress(pixels, level)
    step = -(-len(packed) // pieces)
    data = b"".join(_chunk(b"IDAT", packed[at:at + step]) for at in range(0, len(packed), step))
    time = _chunk(b"tIME", stamp) if stamp else b""
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + time + data + _chunk(b"IEND", b"")


BLACK = b"\x00\x00\x00\x00\x00\x00"
WHITE = b"\x00\xff\xff\x00\xff\xff"


def test_the_same_picture_in_a_different_file_is_the_same_frame():
    plain = read_frame(png(BLACK))
    assert plain.of == "pixels"
    assert read_frame(png(BLACK, stamp=b"\x07\xea\x0b\x1c\x11\x00\x00")) == plain
    assert read_frame(png(BLACK, packed_as=(0, 1))) == plain
    assert read_frame(png(BLACK * 40, size=(2, 80), packed_as=(6, 3))) == read_frame(png(BLACK * 40, size=(2, 80)))


def test_a_different_picture_is_a_different_frame():
    assert read_frame(png(WHITE)).digest != read_frame(png(BLACK)).digest
    # The same bytes laid out as another shape are another picture.
    assert read_frame(png(BLACK, size=(1, 4))).digest != read_frame(png(BLACK)).digest


def test_what_follows_the_end_marker_is_not_part_of_the_picture():
    assert read_frame(png(BLACK) + _chunk(b"IHDR", b"\x01" * 13)) == read_frame(png(BLACK))


def test_a_file_cut_off_before_its_end_marker_is_read_up_to_its_last_whole_chunk():
    whole = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", b"\x00" * 13) + _chunk(b"IDAT", b"")
    assert read_frame(whole).of == "pixels"
    # One byte short of a whole chunk: the data chunk is not there, so there is no picture to read.
    assert read_frame(whole[:-1]).of == "bytes"


@pytest.mark.parametrize("broken", [
    b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", b"\x00" * 13) + _chunk(b"IDAT", b"not deflate") + _chunk(b"IEND", b""),
    b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", b"\x00" * 13) + _chunk(b"IEND", b""),
    b"\x89PNG\r\n\x1a\n" + _chunk(b"IDAT", zlib.compress(BLACK)) + _chunk(b"IEND", b""),
    b"\x89PNG\r\n\x1a\n",
    b"\x89PNG\r\n\x1a\n\x00\x00",
])
def test_a_png_with_no_readable_picture_is_compared_by_its_bytes(broken):
    frame = read_frame(broken)
    assert frame.of == "bytes"
    assert frame == read_frame(bytes(broken))
    assert frame.digest != read_frame(broken + b"\x00").digest


def test_a_bitmap_is_its_pixels_and_anything_else_is_bytes():
    assert read_frame(b"BM" + BLACK).of == "pixels"
    assert read_frame(b"BM" + BLACK).digest != read_frame(b"BM" + WHITE).digest
    assert read_frame(b"\xff\xd8\xff jpeg").of == "bytes"
    assert read_frame(b"").of == "bytes"


@pytest.mark.parametrize(("before", "after", "how"), [
    ("pixels", "pixels", "pixels"), ("pixels", "bytes", "bytes"), ("bytes", "pixels", "bytes"),
    ("bytes", "bytes", "bytes"),
])
def test_two_frames_are_compared_as_pixels_only_when_both_are(before, after, how):
    assert compared_as(Frame("a", before), Frame("b", after)) == how


def _windows(*lists, tool="wmctrl", attempts=None):
    """A lister that answers with each list in turn; the last one repeats."""
    given = list(lists)

    async def listing():
        return {"ok": True, "tool": tool, "windows": given.pop(0) if len(given) > 1 else given[0],
                "attempts": attempts}

    return listing


def _front(*windows):
    given = list(windows)

    async def active():
        return given.pop(0) if len(given) > 1 else given[0]

    return active


def _look(look) -> Look:
    return asyncio.run(look())


def _want(**fields):
    return {"title": "", "class": "", "state": "present", **fields}


def test_a_window_is_present_when_one_matches_and_the_best_match_is_named():
    look = window_look(_want(title="MINECRAFT"), _windows([NOTES], [NOTES, GAME_SMALL, GAME]), _front(None))
    assert _look(look) == Look(False, {"matches": 0})
    assert _look(look) == Look(True, {"matches": 2, "window": GAME})


def test_a_window_is_matched_by_its_class_too():
    look = window_look(_want(**{"class": "glfw"}), _windows([NOTES, GAME]), _front(None))
    assert _look(look) == Look(True, {"matches": 1, "window": GAME})
    both = window_look(_want(title="minecraft", **{"class": "editor"}), _windows([NOTES, GAME]), _front(None))
    assert _look(both) == Look(False, {"matches": 0})


def test_a_window_is_absent_when_none_matches_and_the_one_still_there_is_named():
    look = window_look(_want(title="minecraft", state="absent"), _windows([GAME, NOTES], [NOTES]), _front(None))
    assert _look(look) == Look(False, {"matches": 1, "window": GAME})
    assert _look(look) == Look(True, {"matches": 0})


def test_a_window_is_active_when_the_one_in_front_matches():
    look = window_look(_want(title="minecraft", state="active"), _windows([GAME, NOTES]), _front(NOTES, GAME))
    assert _look(look) == Look(False, {"active_window": NOTES})
    assert _look(look) == Look(True, {"window": GAME})


def test_nothing_in_front_is_not_yet_while_the_windows_can_be_listed():
    look = window_look(_want(title="minecraft", state="active"), _windows([GAME]), _front(None))
    assert _look(look) == Look(False, {"active_window": None})


@pytest.mark.parametrize("state", ["present", "absent", "active"])
def test_a_desktop_whose_windows_cannot_be_listed_is_not_an_empty_desktop(state):
    """Else every wait for a window to go away would succeed at once on a headless host."""
    look = window_look(_want(title="x", state=state), _windows([], tool="none"), _front(None))
    with pytest.raises(CannotLook) as failed:
        _look(look)
    assert failed.value.result["ok"] is False
    assert failed.value.result["unavailable"] == ["wmctrl", "xdotool"]
    assert failed.value.result["error"].startswith("no tool to list windows")


@pytest.mark.parametrize("attempts", [[], [{"tool": "wmctrl", "ok": False}], [{"tool": "kwin_script", "ok": False},
                                                                             {"tool": "xdotool", "ok": None}], [{}]])
def test_a_lister_that_was_tried_and_failed_did_not_list_either(attempts):
    look = window_look(_want(title="x", state="absent"), _windows([], tool="none", attempts=attempts), _front(None))
    with pytest.raises(CannotLook) as failed:
        _look(look)
    assert failed.value.result["unavailable"] == ["wmctrl", "xdotool"]


@pytest.mark.parametrize(("state", "seen"), [
    ("present", Look(False, {"matches": 0})),
    ("absent", Look(True, {"matches": 0})),
    ("active", Look(False, {"active_window": None})),
])
def test_a_lister_that_ran_and_found_no_window_is_an_empty_desktop(state, seen):
    """wmctrl on a session with no windows: the catalog names no tool, and lists the run among its attempts."""
    ran = [{"tool": "kwin_script", "ok": False}, {"tool": "wmctrl", "ok": True, "stderr": ""}]
    look = window_look(_want(title="x", state=state), _windows([], tool="none", attempts=ran), _front(None))
    assert _look(look) == seen


BARE = {"id": "0x1", "title": "Abyssal Ascent - Minecraft", "pid": "7", "geometry": {"width": 800, "height": 600}}


@pytest.mark.parametrize("state", ["present", "absent", "active"])
def test_a_class_is_refused_where_the_window_list_has_no_classes(state):
    """Else `absent` is true at once and `present` never, with the window on the screen all the while."""
    look = window_look(_want(state=state, **{"class": "glfw"}), _windows([GAME, BARE]), _front(BARE))
    with pytest.raises(CannotLook) as failed:
        _look(look)
    assert failed.value.result == {"ok": False, "error": (
        "the window list on this host does not say which class a window has, so 'class' cannot be matched here: "
        "wait by 'title' instead")}


def test_a_title_alone_is_matched_on_a_window_list_with_no_classes():
    look = window_look(_want(title="minecraft"), _windows([BARE]), _front(None))
    assert _look(look) == Look(True, {"matches": 1, "window": BARE})


def test_a_class_is_read_from_either_place_a_window_record_keeps_it():
    kwin = {"id": "k", "title": "Notes", "resource_class": "org.kde.kate", "geometry": {"width": 9, "height": 9}}
    look = window_look(_want(**{"class": "kate"}), _windows([GAME, kwin]), _front(None))
    assert _look(look) == Look(True, {"matches": 1, "window": kwin})
    # No window at all has no class to miss.
    assert _look(window_look(_want(**{"class": "kate"}), _windows([]), _front(None))) == Look(False, {"matches": 0})


@pytest.mark.parametrize("state", ["present", "absent", "active"])
def test_a_listing_that_failed_is_handed_on_as_it_is(state):
    async def listing():
        return {"ok": False, "error": "EnumWindows failed", "windows": []}

    look = window_look(_want(title="x", state=state), listing, _front(None))
    with pytest.raises(CannotLook) as failed:
        _look(look)
    assert failed.value.result == {"ok": False, "error": "EnumWindows failed", "windows": []}


def test_the_listing_is_not_asked_while_something_is_in_front():
    async def listing():
        raise AssertionError("the active window was known; nothing else needed asking")

    assert _look(window_look(_want(title="notes", state="active"), listing, _front(NOTES))).done is True


class Screen:
    """A capture function showing the pictures it is given in turn; the last one stays."""

    def __init__(self, *pictures: bytes) -> None:
        """Remember the pictures and which regions were asked for."""
        self.pictures = list(pictures)
        self.regions: list = []

    async def __call__(self, region):
        self.regions.append(region)
        picture = self.pictures.pop(0) if len(self.pictures) > 1 else self.pictures[0]
        return {"ok": True, "bytes": picture, "encoding": "png", "captured_region": region}


def test_the_screen_has_changed_when_it_differs_from_the_first_look():
    screen = Screen(png(BLACK), png(BLACK, stamp=b"\x07\xea\x0b\x1c\x11\x00\x01"), png(WHITE))
    region = {"x": 1, "y": 2, "width": 3, "height": 4}
    look = screen_look({"until": "change", "stable_ms": 1000, "region": region}, screen)
    assert _look(look) == Look(False, {"compared": "pixels"})
    assert _look(look) == Look(False, {"compared": "pixels"})
    assert _look(look) == Look(True, {"compared": "pixels"})
    assert screen.regions == [region, region, region]


def test_a_change_is_measured_from_the_first_look_not_from_the_previous_one():
    """Black, white, black again: the third look is the first picture, so nothing has changed since the call."""
    look = screen_look({"until": "change", "stable_ms": 1000, "region": None}, Screen(png(BLACK), png(BLACK)))
    assert [_look(look).done, _look(look).done] == [False, False]
    back = screen_look({"until": "change", "stable_ms": 1000, "region": None},
                       Screen(png(BLACK), png(WHITE), png(BLACK)))
    assert [_look(back).done, _look(back).done, _look(back).done] == [False, True, False]


def test_a_capture_that_is_not_a_picture_says_it_was_compared_as_bytes():
    look = screen_look({"until": "change", "stable_ms": 1000, "region": None}, Screen(b"jpeg one", b"jpeg two"))
    assert _look(look) == Look(False, {"compared": "bytes"})
    assert _look(look) == Look(True, {"compared": "bytes"})


def test_the_screen_is_stable_once_it_has_not_changed_for_long_enough():
    now = [50.0]
    screen = Screen(png(BLACK), png(WHITE), png(WHITE), png(WHITE, packed_as=(1, 1)))
    look = screen_look({"until": "stable", "stable_ms": 1000, "region": None}, screen, clock=lambda: now[0])
    seen = []
    for at in (50.0, 50.5, 51.0, 51.499, 51.5):
        now[0] = at
        seen.append(_look(look))
    assert seen == [
        Look(False, {"still_ms": 0, "compared": "pixels"}),
        Look(False, {"still_ms": 0, "compared": "pixels"}),     # it changed: the count starts again
        Look(False, {"still_ms": 500, "compared": "pixels"}),
        Look(False, {"still_ms": 999, "compared": "pixels"}),
        Look(True, {"still_ms": 1000, "compared": "pixels"}),
    ]
    assert screen.regions == [None] * 5


@pytest.mark.parametrize("until", ["change", "stable"])
def test_a_capture_that_failed_is_handed_on_as_it_is(until):
    async def capture(_region):
        return {"ok": False, "error": "no screenshot tool", "unavailable": ["grim"]}

    with pytest.raises(CannotLook) as failed:
        _look(screen_look({"until": until, "stable_ms": 1000, "region": None}, capture))
    assert failed.value.result == {"ok": False, "error": "no screenshot tool", "unavailable": ["grim"]}


@pytest.mark.parametrize("until", ["change", "stable"])
@pytest.mark.parametrize("shot", [
    {"ok": True, "bytes": b"BM whole desktop", "captured_region": None},
    {"ok": True, "bytes": b"BM whole desktop"},
])
def test_a_capture_that_was_not_cut_to_the_region_is_not_watched_instead(until, shot):
    """Without Pillow the whole desktop comes back; a change anywhere on it would be reported for the region."""
    async def capture(_region):
        return shot

    region = {"x": 0, "y": 0, "width": 10, "height": 10}
    with pytest.raises(CannotLook) as failed:
        _look(screen_look({"until": until, "stable_ms": 1000, "region": region}, capture))
    assert failed.value.result == {"ok": False, "unavailable": ["pillow"], "error": (
        "the capture could not be cut to the region, so it shows the whole desktop: on this host that needs the "
        "Pillow package (pip install Pillow)")}
    # The same capture is what was asked for when no region was.
    assert _look(screen_look({"until": until, "stable_ms": 1000, "region": None}, capture)).done is False


def _reader(*answers):
    given = list(answers)
    asked = []

    async def find_text(want):
        asked.append(want)
        return given.pop(0) if len(given) > 1 else given[0]

    return find_text, asked


MATCH = {"text": "Singleplayer", "bbox": {"x": 1, "y": 2, "width": 3, "height": 4}}


def test_text_is_present_when_the_reader_finds_it():
    want = {"text": "singleplayer", "state": "present", "region": None, "min_confidence": 40}
    find_text, asked = _reader({"ok": True, "matches": [], "word_count": 12},
                               {"ok": True, "matches": [MATCH, {"text": "other"}], "word_count": 30})
    look = text_look(want, find_text)
    assert _look(look) == Look(False, {"matches": 0, "word_count": 12})
    assert _look(look) == Look(True, {"matches": 2, "word_count": 30, "match": MATCH})
    assert asked == [want, want]


def test_text_is_absent_when_the_reader_no_longer_finds_it():
    want = {"text": "loading", "state": "absent", "region": None, "min_confidence": 40}
    find_text, _ = _reader({"ok": True, "matches": [MATCH], "word_count": 5}, {"ok": True, "word_count": 4})
    look = text_look(want, find_text)
    assert _look(look) == Look(False, {"matches": 1, "word_count": 5, "match": MATCH})
    assert _look(look) == Look(True, {"matches": 0, "word_count": 4})


def test_a_reader_with_no_word_count_reports_none_read():
    find_text, _ = _reader({"ok": True, "matches": None})
    want = {"text": "x", "state": "present", "region": None, "min_confidence": 40}
    assert _look(text_look(want, find_text)) == Look(False, {"matches": 0, "word_count": 0})


def test_words_read_from_the_whole_desktop_do_not_answer_for_a_region():
    region = {"x": 5, "y": 5, "width": 50, "height": 20}
    want = {"text": "x", "state": "present", "region": region, "min_confidence": 40}
    whole, _ = _reader({"ok": True, "matches": [MATCH], "word_count": 9, "captured_region": None})
    with pytest.raises(CannotLook) as failed:
        _look(text_look(want, whole))
    assert failed.value.result["unavailable"] == ["pillow"]
    cut, _ = _reader({"ok": True, "matches": [MATCH], "word_count": 2, "captured_region": region})
    assert _look(text_look(want, cut)).done is True
    assert _look(text_look({**want, "region": None}, whole)).done is True


def test_a_reader_that_failed_is_handed_on_as_it_is():
    refusal = {"ok": False, "error": "tesseract is not installed", "unavailable": ["tesseract"]}
    find_text, _ = _reader(refusal)
    with pytest.raises(CannotLook) as failed:
        _look(text_look({"text": "x", "state": "absent", "region": None, "min_confidence": 40}, find_text))
    assert failed.value.result == refusal

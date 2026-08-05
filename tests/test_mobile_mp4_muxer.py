"""The H.264 -> fMP4 muxer, exercised with real bitstream bytes.

`arena/mobile/mp4_muxer.py` is 576 lines that turn what screenrecord
emits into what a browser's MediaSource can play, and it had no tests at
all. Everything downstream of it -- the whole live mirror -- is only as
correct as this file, and "the live view is black" is exactly the kind of
failure that looks like a UI bug for a week.

The SPS/PPS below are real Annex-B parameter sets, so `parse_sps` is
doing genuine exp-Golomb decoding rather than reading a fixture someone
wrote to match the parser.

Sabotage record (mandatory per AGENTS.md):
  1. `parse_sps` returning fixed 1920x1080
     -> test_sps_dimensions_come_from_the_bitstream fails.
  2. emitting the init segment before PPS arrives
     -> test_init_waits_for_both_parameter_sets fails.
  3. dropping the keyframe flag on IDR
     -> test_idr_is_reported_as_a_keyframe fails.
  4. fixed frame duration instead of wall-clock pacing
     -> test_decode_time_advances_monotonically still passes, which is
        why test_sample_duration_tracks_wall_clock exists.
"""
from __future__ import annotations

import struct
import time

import pytest

from arena.mobile.mp4_muxer import H264ToFMP4, parse_sps

# Real Annex-B parameter sets (Main profile, level 3.1).
SPS = bytes.fromhex("674d401f96540a0fd8080f162ae0202028000003000800000301e078c195")
PPS = bytes.fromhex("68ebef20")

START_CODE = b"\x00\x00\x00\x01"


def _nal(payload: bytes) -> bytes:
    return START_CODE + payload


def _idr(size: int = 200) -> bytes:
    return _nal(bytes([0x65]) + b"\x11" * size)


def _pframe(size: int = 100) -> bytes:
    return _nal(bytes([0x41]) + b"\x22" * size)


class _Sink:
    def __init__(self) -> None:
        self.inits: list[bytes] = []
        self.fragments: list[tuple[bytes, bool]] = []

    def muxer(self, **kwargs) -> H264ToFMP4:
        return H264ToFMP4(on_init=self.inits.append,
                          on_fragment=lambda b, k: self.fragments.append((b, k)),
                          **kwargs)


def _box_offset(buf: bytes, name: bytes) -> int:
    index = buf.find(name)
    assert index > 0, f"{name!r} box missing"
    return index


def _decode_time(fragment: bytes) -> int:
    offset = _box_offset(fragment, b"tfdt")
    version = fragment[offset + 4]
    if version == 1:
        return struct.unpack(">Q", fragment[offset + 8:offset + 16])[0]
    return struct.unpack(">I", fragment[offset + 8:offset + 12])[0]


def _sample_duration(fragment: bytes) -> int:
    offset = _box_offset(fragment, b"trun")
    return struct.unpack(">I", fragment[offset + 16:offset + 20])[0]


# ---------------------------------------------------------------------------
# SPS parsing.
# ---------------------------------------------------------------------------

def test_sps_dimensions_come_from_the_bitstream():
    info = parse_sps(SPS)
    assert (info.width, info.height) == (320, 240)
    assert info.profile_idc == 77
    assert info.level_idc == 31


def test_a_truncated_sps_does_not_crash_the_pipeline():
    """A partial NAL at a segment boundary must not kill the stream."""
    sink = _Sink()
    mux = sink.muxer()
    mux.feed(_nal(SPS[:4]) + _nal(PPS))
    mux.feed(_idr())
    mux.flush()
    # No init is fine; a traceback out of feed() is not.


# ---------------------------------------------------------------------------
# Init segment.
# ---------------------------------------------------------------------------

def test_init_waits_for_both_parameter_sets():
    """ftyp+moov cannot be built from SPS alone -- decoding needs the PPS."""
    sink = _Sink()
    mux = sink.muxer()

    # An Annex-B splitter only completes a NAL when it sees the NEXT
    # start code, so each feed here is followed by one. That is correct
    # framing, not a quirk: the last NAL of a chunk is genuinely
    # incomplete until more bytes arrive.
    mux.feed(_nal(SPS) + START_CODE)
    assert sink.inits == [], "init emitted before the PPS arrived"

    mux.feed(PPS + _idr())
    assert len(sink.inits) == 1


def test_init_segment_is_a_well_formed_fmp4_header():
    sink = _Sink()
    mux = sink.muxer()
    mux.feed(_nal(SPS) + _nal(PPS) + _idr())
    mux.flush()

    init = sink.inits[0]
    assert init[4:8] == b"ftyp"
    for box in (b"moov", b"mvhd", b"trak", b"mvex", b"avcC"):
        assert box in init, f"{box!r} missing from the init segment"
    # The avcC record must carry the exact parameter sets we fed in.
    assert SPS in init and PPS in init


def test_init_is_emitted_once_per_parameter_set_change():
    sink = _Sink()
    mux = sink.muxer()
    mux.feed(_nal(SPS) + _nal(PPS) + _idr())
    mux.feed(_pframe())
    mux.flush()
    assert len(sink.inits) == 1, "init re-emitted for an unchanged stream"


# ---------------------------------------------------------------------------
# Fragments.
# ---------------------------------------------------------------------------

def test_idr_is_reported_as_a_keyframe():
    """The mirror caches this to seed late joiners; get it wrong and they
    see a black `<video>` until the next screenrecord restart."""
    sink = _Sink()
    mux = sink.muxer()
    mux.feed(_nal(SPS) + _nal(PPS) + _idr())
    mux.feed(_pframe())
    mux.flush()

    kinds = [is_key for _, is_key in sink.fragments]
    assert kinds[0] is True, "the IDR was not flagged as a keyframe"
    assert kinds[1] is False, "a P-frame was flagged as a keyframe"


def test_each_fragment_is_moof_plus_mdat():
    sink = _Sink()
    mux = sink.muxer()
    mux.feed(_nal(SPS) + _nal(PPS) + _idr())
    mux.flush()

    payload = sink.fragments[0][0]
    assert payload[4:8] == b"moof"
    assert b"mdat" in payload
    assert b"tfhd" in payload and b"tfdt" in payload and b"trun" in payload


def test_decode_time_advances_monotonically():
    """A timeline that goes backwards makes MediaSource stall."""
    sink = _Sink()
    mux = sink.muxer()
    mux.feed(_nal(SPS) + _nal(PPS) + _idr())
    for _ in range(5):
        mux.feed(_pframe())
    mux.flush()

    times = [_decode_time(payload) for payload, _ in sink.fragments]
    assert times[0] == 0
    assert times == sorted(times)
    assert len(set(times)) == len(times), "two fragments share a decode time"


def test_sample_duration_tracks_wall_clock():
    """Fixed durations drift: Android emits more access units than the
    display refresh, so the MP4 timeline outruns real time and the video
    falls further behind every minute. Durations must follow the clock.
    """
    sink = _Sink()
    mux = sink.muxer()
    mux.feed(_nal(SPS) + _nal(PPS) + _idr())

    for _ in range(4):
        time.sleep(0.05)          # ~20 fps
        mux.feed(_pframe())
    mux.flush()

    # Skip the first fragment: it has no predecessor to measure against.
    durations = [_sample_duration(p) for p, _ in sink.fragments[1:]]
    timescale = mux.timescale
    seconds = [d / timescale for d in durations]
    measured = [s for s in seconds if s > 0.001]
    assert measured, "no fragment carried a measurable duration"
    average = sum(measured) / len(measured)
    assert 0.02 <= average <= 0.20, (
        f"sample durations average {average:.3f}s for frames fed 0.05s "
        "apart -- the timeline is not tracking wall-clock time"
    )


def test_reset_starts_a_new_init_without_losing_the_timeline():
    """`mux.reset()` runs between screenrecord segments every 170s."""
    sink = _Sink()
    mux = sink.muxer()
    mux.feed(_nal(SPS) + _nal(PPS) + _idr())
    mux.feed(_pframe())
    mux.flush()
    before = len(sink.fragments)

    mux.reset()
    mux.feed(_nal(SPS) + _nal(PPS) + _idr())
    mux.flush()

    assert len(sink.inits) == 2, "reset did not re-emit an init segment"
    assert len(sink.fragments) > before


# ---------------------------------------------------------------------------
# Framing robustness -- screenrecord's stdout arrives in arbitrary chunks.
# ---------------------------------------------------------------------------

def test_nals_split_across_reads_are_reassembled():
    """`read(65536)` cuts wherever it likes, including mid-start-code."""
    stream = _nal(SPS) + _nal(PPS) + _idr() + _pframe()

    whole = _Sink()
    mux = whole.muxer()
    mux.feed(stream)
    mux.flush()

    for chunk_size in (1, 3, 7, 64, 511):
        split = _Sink()
        mux = split.muxer()
        for start in range(0, len(stream), chunk_size):
            mux.feed(stream[start:start + chunk_size])
        mux.flush()

        assert len(split.inits) == len(whole.inits), (
            f"chunk size {chunk_size} changed the init count"
        )
        assert len(split.fragments) == len(whole.fragments), (
            f"chunk size {chunk_size} changed the fragment count"
        )


@pytest.mark.parametrize("start_code", [b"\x00\x00\x01", b"\x00\x00\x00\x01"])
def test_both_three_and_four_byte_start_codes_are_accepted(start_code):
    """Android emits both forms in the same stream."""
    sink = _Sink()
    mux = sink.muxer()
    mux.feed(start_code + SPS + start_code + PPS
             + start_code + bytes([0x65]) + b"\x11" * 100)
    mux.flush()

    assert len(sink.inits) == 1
    assert len(sink.fragments) == 1


def test_garbage_before_the_first_start_code_is_skipped():
    """Attaching mid-stream hands us a partial NAL first."""
    sink = _Sink()
    mux = sink.muxer()
    mux.feed(b"\xde\xad\xbe\xef" + _nal(SPS) + _nal(PPS) + _idr())
    mux.flush()

    assert len(sink.inits) == 1
    assert len(sink.fragments) >= 1


def test_an_empty_feed_is_harmless():
    sink = _Sink()
    mux = sink.muxer()
    mux.feed(b"")
    mux.flush()
    assert sink.inits == [] and sink.fragments == []

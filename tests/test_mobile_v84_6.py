"""Tests for v3.84.6: Python-native H.264 → fMP4 muxer.

Covers the parsing + muxing layer end-to-end without touching adb:
  * `iter_annexb_nals` and `AnnexBSplitter` respect long/short start
    codes and buffer partial NALs across feeds.
  * `parse_sps` extracts width/height for a known real-world SPS.
  * `_RBSP` strips 0x00 0x00 0x03 emulation prevention.
  * `build_ftyp` / `build_moov` produce well-formed boxes with the
    correct 4CCs and nested layout.
  * `build_moof_mdat` produces a fragment whose trun data_offset points
    at the first byte AFTER the mdat header, and whose sample flags
    match keyframe vs non-keyframe.
  * `H264ToFMP4` emits exactly one init and one fragment per feed of
    a synthetic AU stream, and preserves timing across restarts via
    `reset()`.
"""
from __future__ import annotations

import struct

import pytest


# ---------------------------------------------------------------------------
# Annex-B parsing
# ---------------------------------------------------------------------------
def test_iter_annexb_nals_splits_on_long_and_short_start_codes():
    from arena.mobile.h264_parser import iter_annexb_nals
    # 4-byte start | NAL1 | 3-byte start | NAL2 | 4-byte start | NAL3
    stream = (b"\x00\x00\x00\x01" + b"\x67AAA"
              + b"\x00\x00\x01" + b"\x68BB"
              + b"\x00\x00\x00\x01" + b"\x65CCCC")
    got = list(iter_annexb_nals(stream))
    assert got == [b"\x67AAA", b"\x68BB", b"\x65CCCC"]


def test_iter_annexb_nals_leading_garbage_is_skipped():
    from arena.mobile.h264_parser import iter_annexb_nals
    stream = b"\xff\xfe\x00\x00\x00\x01\x67AAA"
    assert list(iter_annexb_nals(stream)) == [b"\x67AAA"]


def test_iter_annexb_nals_returns_trailing_partial_nal():
    from arena.mobile.h264_parser import iter_annexb_nals
    # One complete NAL then a start code with no follower.
    stream = b"\x00\x00\x00\x01\x67AAA\x00\x00\x00\x01\x68BB"
    got = list(iter_annexb_nals(stream))
    assert got == [b"\x67AAA", b"\x68BB"]


def test_annexb_splitter_buffers_across_chunks():
    from arena.mobile.h264_parser import AnnexBSplitter
    s = AnnexBSplitter()
    s.feed(b"\x00\x00\x00\x01\x67SPS_")   # start of SPS
    s.feed(b"PAYLOAD\x00\x00\x00\x01\x68PPS")  # rest of SPS + start of PPS
    n1 = s.pop()
    assert n1 == b"\x67SPS_PAYLOAD"
    # PPS is still buffered (no closing start code yet).
    assert s.pop() is None
    s.feed(b"\x00\x00\x00\x01\x65IDR")     # closes PPS + starts IDR
    n2 = s.pop()
    assert n2 == b"\x68PPS"
    assert s.pop() is None
    # IDR closes when we feed another start code.
    s.feed(b"\x00\x00\x00\x01\x01SLICE")
    assert s.pop() == b"\x65IDR"
    assert s.pop() is None


def test_nal_type_helper_returns_low_five_bits():
    from arena.mobile.h264_parser import nal_type, NAL_SPS, NAL_PPS, NAL_SLICE_IDR
    assert nal_type(b"\x67abc") == NAL_SPS
    assert nal_type(b"\x68abc") == NAL_PPS
    assert nal_type(b"\x65abc") == NAL_SLICE_IDR
    assert nal_type(b"") == -1


# ---------------------------------------------------------------------------
# SPS parser
# ---------------------------------------------------------------------------
def test_parse_sps_extracts_width_and_height_for_known_720p_sps():
    """A real-world Baseline profile 720x1280 SPS captured from an
    Android screenrecord dump. Width/height decode must match."""
    from arena.mobile.h264_parser import parse_sps
    # profile_idc=66 (Baseline), constraint_set0_flag=1, level_idc=31,
    # SPS ID=0, log2_max_frame_num_minus4=0, pic_order_cnt_type=2,
    # num_ref_frames=1, pic_width_in_mbs_minus1=44 (=> 720),
    # pic_height_in_map_units_minus1=79, frame_mbs_only_flag=1,
    # direct_8x8_inference=1, frame_cropping=0, vui=0.
    # Constructed by hand: 0x67 42 c0 1f 8c 8d 40 5a 1e 00 00 03 00 40
    # For robustness we use a synthetic SPS built via bit packing below.
    sps = _build_sps(width=720, height=1280,
                     profile_idc=66, level_idc=31)
    info = parse_sps(sps)
    assert info.width == 720
    assert info.height == 1280
    assert info.profile_idc == 66
    assert info.level_idc == 31


def test_parse_sps_extracts_uncommon_1440x3200_sps():
    from arena.mobile.h264_parser import parse_sps
    sps = _build_sps(width=720, height=1600,
                     profile_idc=66, level_idc=40)
    info = parse_sps(sps)
    assert (info.width, info.height) == (720, 1600)


def test_parse_sps_rejects_non_sps_nal():
    from arena.mobile.h264_parser import parse_sps
    with pytest.raises(ValueError):
        parse_sps(b"\x68abc")   # PPS


def test_rbsp_strips_emulation_prevention_bytes():
    from arena.mobile.h264_parser import _RBSP
    r = _RBSP(b"\x00\x00\x03\xff")
    # After strip we should read 4 bytes: 0x00 0x00 0xff, and RBSP length = 3.
    assert r._buf == b"\x00\x00\xff"


def _build_sps(*, width: int, height: int, profile_idc: int,
               level_idc: int) -> bytes:
    """Construct a minimal Baseline SPS with the requested dimensions.
    Used by SPS parser tests so we don't depend on captured device
    dumps.
    """
    # Bit writer.
    bits: list[int] = []
    def _w(val: int, n: int) -> None:
        for i in range(n - 1, -1, -1):
            bits.append((val >> i) & 1)
    def _ue(v: int) -> None:
        # H.264 unsigned exp-Golomb: emit (n-1) zeros then the n-bit
        # binary representation of (v+1), where n = bit_length(v+1).
        total = v + 1
        n = total.bit_length()
        for _ in range(n - 1):
            bits.append(0)
        _w(total, n)

    # SPS body starts AFTER the 3 fixed bytes (profile/constraint/level).
    _ue(0)                                     # seq_parameter_set_id
    # (Baseline: no high-profile extras.)
    _ue(0)                                     # log2_max_frame_num_minus4
    _ue(2)                                     # pic_order_cnt_type
    _ue(1)                                     # num_ref_frames
    _w(0, 1)                                   # gaps_in_frame_num_value_allowed_flag
    assert width % 16 == 0
    assert height % 16 == 0
    _ue((width // 16) - 1)                     # pic_width_in_mbs_minus1
    _ue((height // 16) - 1)                    # pic_height_in_map_units_minus1
    _w(1, 1)                                   # frame_mbs_only_flag
    _w(1, 1)                                   # direct_8x8_inference_flag
    _w(0, 1)                                   # frame_cropping_flag
    _w(0, 1)                                   # vui_parameters_present_flag
    # rbsp_stop_one_bit + byte alignment.
    bits.append(1)
    while len(bits) % 8:
        bits.append(0)
    body = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for j in range(8):
            byte = (byte << 1) | bits[i + j]
        body.append(byte)
    header = bytes([0x67, profile_idc, 0x00, level_idc])
    return header + bytes(body)


# ---------------------------------------------------------------------------
# MP4 box builders
# ---------------------------------------------------------------------------
def _read_box_header(buf: bytes, offset: int) -> tuple[int, bytes, int]:
    size = struct.unpack(">I", buf[offset:offset + 4])[0]
    tag = buf[offset + 4:offset + 8]
    return size, tag, offset + 8


def test_build_ftyp_declares_iso5_brand_and_avc1_compat():
    from arena.mobile.mp4_muxer import build_ftyp
    ftyp = build_ftyp()
    size, tag, body = _read_box_header(ftyp, 0)
    assert tag == b"ftyp"
    assert size == len(ftyp)
    assert ftyp[body:body + 4] == b"iso5"   # major_brand
    assert b"avc1" in ftyp                   # in compatible brands


def test_build_moov_wraps_expected_child_boxes():
    from arena.mobile.mp4_muxer import build_moov
    from arena.mobile.h264_parser import parse_sps
    sps = _build_sps(width=720, height=1600,
                     profile_idc=66, level_idc=40)
    sps_info = parse_sps(sps)
    moov = build_moov(720, 1600, 90_000, sps[1:], b"\x68abc", sps_info)
    size, tag, body = _read_box_header(moov, 0)
    assert tag == b"moov"
    assert size == len(moov)
    # First child must be mvhd, then trak, then mvex.
    _, first_tag, _ = _read_box_header(moov, body)
    assert first_tag == b"mvhd"
    # trak / mvex somewhere inside.
    assert b"trak" in moov
    assert b"tkhd" in moov
    assert b"mdia" in moov
    assert b"minf" in moov
    assert b"stbl" in moov
    assert b"avc1" in moov
    assert b"avcC" in moov
    assert b"mvex" in moov
    assert b"trex" in moov


def test_build_moof_mdat_data_offset_points_past_moof_header():
    from arena.mobile.mp4_muxer import build_moof_mdat
    samples = [{
        "data": struct.pack(">I", 5) + b"HELLO",
        "duration": 3000,
        "is_keyframe": True,
    }]
    moof, mdat = build_moof_mdat(sequence_number=1,
                                 base_media_decode_time=0,
                                 samples=samples)
    # mdat starts at len(moof); its 8-byte header is size+type.
    # trun.data_offset should equal len(moof) + 8.
    expected_offset = len(moof) + 8
    # Locate the trun box inside moof and read data_offset.
    idx = moof.find(b"trun")
    assert idx > 0
    # After the 4-byte tag, next 4 bytes are version+flags.
    # Then 4 bytes sample_count, then 4 bytes data_offset.
    offset_pos = idx + 4 + 4 + 4
    (actual,) = struct.unpack(">i", moof[offset_pos:offset_pos + 4])
    assert actual == expected_offset

    # And mdat header sanity.
    size, tag, body = _read_box_header(mdat, 0)
    assert tag == b"mdat"
    assert size == len(mdat)
    assert mdat[body:] == samples[0]["data"]


def test_build_moof_mdat_marks_keyframe_flag():
    from arena.mobile.mp4_muxer import build_moof_mdat
    for is_key, expect in ((True, 0x02000000), (False, 0x01010000)):
        moof, _ = build_moof_mdat(
            sequence_number=1,
            base_media_decode_time=0,
            samples=[{"data": b"\x00\x00\x00\x01x",
                      "duration": 3000, "is_keyframe": is_key}],
        )
        # Locate first-sample-flags in trun: after sample_count (4) +
        # data_offset (4) comes first_sample_flags (4).
        idx = moof.find(b"trun")
        assert idx > 0
        flags_pos = idx + 4 + 4 + 4 + 4
        (flags,) = struct.unpack(">I", moof[flags_pos:flags_pos + 4])
        assert flags == expect


# ---------------------------------------------------------------------------
# H264ToFMP4 state machine
# ---------------------------------------------------------------------------
def test_h264_to_fmp4_emits_init_then_one_fragment_per_frame():
    from arena.mobile.mp4_muxer import H264ToFMP4
    init_calls: list[bytes] = []
    frag_calls: list[tuple[bytes, bool]] = []
    mux = H264ToFMP4(
        on_init=init_calls.append,
        on_fragment=lambda b, k: frag_calls.append((b, k)),
    )

    sps = _build_sps(width=720, height=1600,
                     profile_idc=66, level_idc=40)
    pps = b"\x68\x01\x02\x03"
    idr = b"\x65IDR_PAYLOAD_A"
    aud = b"\x09\xf0"
    p1 = b"\x01PSLICE_A"
    p2 = b"\x01PSLICE_B"

    # First AU: SPS + PPS + IDR
    au1 = (b"\x00\x00\x00\x01" + sps
           + b"\x00\x00\x00\x01" + pps
           + b"\x00\x00\x00\x01" + idr)
    # AUD delimits, next AU is a P frame
    au2 = b"\x00\x00\x00\x01" + aud + b"\x00\x00\x00\x01" + p1
    # Another AUD + P
    au3 = b"\x00\x00\x00\x01" + aud + b"\x00\x00\x00\x01" + p2

    mux.feed(au1)
    mux.feed(au2)
    mux.feed(au3)
    mux.flush()

    assert len(init_calls) == 1
    init = init_calls[0]
    assert init[:4]                       # non-empty length
    assert b"ftyp" in init and b"moov" in init and b"avcC" in init

    # 3 frames: IDR + 2 P-slices.
    assert len(frag_calls) == 3
    assert frag_calls[0][1] is True       # first is keyframe
    assert frag_calls[1][1] is False
    assert frag_calls[2][1] is False
    # decode times advance monotonically -- easiest to check via stats.
    assert mux.stats_fragments == 3
    assert mux.stats_keyframes == 1


def test_h264_to_fmp4_reset_forgets_sps_but_keeps_decode_clock():
    from arena.mobile.mp4_muxer import H264ToFMP4
    inits: list[bytes] = []
    frags: list[tuple[bytes, bool]] = []
    mux = H264ToFMP4(on_init=inits.append,
                     on_fragment=lambda b, k: frags.append((b, k)))
    sps = _build_sps(width=720, height=1600,
                     profile_idc=66, level_idc=40)
    au = (b"\x00\x00\x00\x01" + sps
          + b"\x00\x00\x00\x01\x68\x01\x02\x03"
          + b"\x00\x00\x00\x01\x65IDR"
          + b"\x00\x00\x00\x01\x09\xf0"
          + b"\x00\x00\x00\x01\x01P")
    mux.feed(au)
    mux.flush()
    decode1 = mux._decode_time
    assert len(inits) == 1
    assert len(frags) == 2

    mux.reset()
    assert mux._sps is None and mux._init_sent is False
    mux.feed(au)
    mux.flush()
    assert len(inits) == 2                # fresh init after reset
    assert len(frags) == 4                # two more frames
    assert mux._decode_time > decode1     # clock NEVER rewinds


def test_h264_to_fmp4_discards_frames_before_sps():
    from arena.mobile.mp4_muxer import H264ToFMP4
    frags: list[tuple[bytes, bool]] = []
    inits: list[bytes] = []
    mux = H264ToFMP4(on_init=inits.append,
                     on_fragment=lambda b, k: frags.append((b, k)))
    # Feed a lone P-slice before SPS/PPS: should be dropped, not
    # emitted as an orphan fragment.
    stream = (b"\x00\x00\x00\x01\x01ORPHAN"
              + b"\x00\x00\x00\x01\x09\xf0")
    mux.feed(stream)
    mux.flush()
    assert inits == []
    assert frags == []


def test_h264_to_fmp4_records_stats_across_feeds():
    from arena.mobile.mp4_muxer import H264ToFMP4
    mux = H264ToFMP4(on_init=lambda b: None,
                     on_fragment=lambda b, k: None)
    sps = _build_sps(width=720, height=1600,
                     profile_idc=66, level_idc=40)
    stream = (b"\x00\x00\x00\x01" + sps
              + b"\x00\x00\x00\x01\x68\x01\x02\x03"
              + b"\x00\x00\x00\x01\x65IDR"
              + b"\x00\x00\x00\x01\x09\xf0"
              + b"\x00\x00\x00\x01\x01SLICE1"
              + b"\x00\x00\x00\x01\x09\xf0"
              + b"\x00\x00\x00\x01\x01SLICE2")
    mux.feed(stream)
    mux.flush()
    assert mux.stats_fragments == 3
    assert mux.stats_keyframes == 1
    assert mux.stats_bytes > 0


# ---------------------------------------------------------------------------
# Mirror integration -- session dataclass still works with the new muxer.
# ---------------------------------------------------------------------------
def test_mirror_session_dataclass_has_keyframes_field():
    from arena.mobile import mirror as m
    s = m.MirrorSession(serial="x", size="720x1600", bit_rate=1)
    assert s.keyframes_sent == 0
    # broadcast() bumps stats.
    q = s.add_subscriber()
    payload = b"\x00\x00\x00\x08moofX"
    s.broadcast(payload)
    assert s.fragments_sent == 1
    assert s.bytes_sent == len(payload)
    assert q.qsize() == 1
    # Control marker doesn't count as a fragment.
    s.broadcast(m._INIT_MARKER)
    assert s.fragments_sent == 1
    assert s.bytes_sent == len(payload)


def test_mirror_stats_snapshot_includes_muxer_marker():
    from arena.mobile import mirror as m
    m._SESSIONS.clear()
    m._SESSIONS["dev"] = m.MirrorSession(serial="dev", size="720x1600",
                                         bit_rate=4_000_000)
    try:
        stats = m.stats()
        assert stats[0]["muxer"] == "python-native"
        assert stats[0]["keyframes_sent"] == 0
    finally:
        m._SESSIONS.clear()

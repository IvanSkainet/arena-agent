"""Fragmented MP4 box builders + H.264 → fMP4 state machine (v3.84.6).

The muxer takes raw Annex-B H.264 bytes (from `screenrecord`) and
produces:

  * one **init segment** (`ftyp + moov`) as soon as the first
    SPS+PPS pair lands. `moov` includes `mvex/trex` so the whole file
    is legal fragmented MP4.

  * one **media segment** (`moof + mdat`) per complete access unit --
    i.e. one fragment per video frame. Emitting a fragment per frame
    (rather than per GOP) is what fixes the v3.84.3 "static screen
    never renders" bug: MediaSource paints the moment we append, even
    for a lone P-frame between two rare IDRs.

`H264ToFMP4` is fed from the ADB reader task and calls
`on_init(bytes)` once + `on_fragment(bytes, is_keyframe)` per frame.

Reference boxes:
  * ISO/IEC 14496-12: ftyp, moov, mvhd, trak, tkhd, mdia, mdhd, hdlr,
                      minf, vmhd, dinf, dref, url, stbl, stsd, stts,
                      stsc, stsz, stco, mvex, trex, moof, mfhd, traf,
                      tfhd, tfdt, trun, mdat.
  * ISO/IEC 14496-15: avc1, avcC (AVCDecoderConfigurationRecord).
"""
from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field
from typing import Callable

from arena.mobile.h264_parser import (
    AnnexBSplitter,
    NAL_AUD,
    NAL_PPS,
    NAL_SEI,
    NAL_SLICE_IDR,
    NAL_SPS,
    SPSInfo,
    VCL_TYPES,
    nal_type,
    parse_sps,
)


# ---------------------------------------------------------------------------
# Box building primitives
# ---------------------------------------------------------------------------

def _box(tag: bytes, payload: bytes) -> bytes:
    """Wrap `payload` in an ISOBMFF box: 32-bit length + 4-byte tag."""
    return struct.pack(">I", 8 + len(payload)) + tag + payload


def _full_box(tag: bytes, version: int, flags: int, payload: bytes) -> bytes:
    header = struct.pack(">BBH",
                         version,
                         (flags >> 16) & 0xFF,
                         flags & 0xFFFF)
    return _box(tag, header + payload)


# ---------------------------------------------------------------------------
# Static parts of the init segment
# ---------------------------------------------------------------------------

def build_ftyp() -> bytes:
    """`ftyp` box for streaming AVC video. `iso5` is the newest brand
    every modern MediaSource implementation groks; the extra brands
    cover fallbacks for slightly older browsers."""
    payload = (
        b"iso5"
        + struct.pack(">I", 512)
        + b"iso5"
        + b"iso6"
        + b"mp41"
        + b"avc1"
    )
    return _box(b"ftyp", payload)


def build_avcc(sps_body: bytes, pps_body: bytes,
               profile_idc: int, constraint_flags: int,
               level_idc: int) -> bytes:
    """AVCDecoderConfigurationRecord body (goes inside an `avcC` box).

    `sps_body` and `pps_body` must be the NAL payloads WITHOUT the
    Annex-B start code AND WITHOUT the 1-byte NAL header -- ISO 14496-15
    requires them stripped in the config record because the NAL header
    is reconstructed by the decoder from a separate byte in the record
    itself.
    """
    return (
        struct.pack(">B", 1)                    # configurationVersion
        + struct.pack(">B", profile_idc)         # AVCProfileIndication
        + struct.pack(">B", constraint_flags)    # profile_compatibility
        + struct.pack(">B", level_idc)           # AVCLevelIndication
        + struct.pack(">B", 0xFF)                # 6 reserved bits + lengthSizeMinusOne=3
        + struct.pack(">B", 0xE1)                # 3 reserved bits + numOfSPS=1
        + struct.pack(">H", len(sps_body)) + sps_body
        + struct.pack(">B", 1)                   # numOfPPS=1
        + struct.pack(">H", len(pps_body)) + pps_body
    )


def build_avc1(width: int, height: int, avcc: bytes) -> bytes:
    """`avc1` sample entry with the `avcC` config record inside."""
    reserved_1 = b"\x00" * 6                    # 6-byte SampleEntry reserved
    data_reference_index = struct.pack(">H", 1)
    pre_defined_1 = struct.pack(">H", 0)
    reserved_2 = struct.pack(">H", 0)
    pre_defined_2 = b"\x00" * 12
    w = struct.pack(">H", width)
    h = struct.pack(">H", height)
    horiz_reso = struct.pack(">I", 0x00480000)   # 72 dpi
    vert_reso = struct.pack(">I", 0x00480000)
    reserved_3 = struct.pack(">I", 0)
    frame_count = struct.pack(">H", 1)
    # 32-byte compressor name: 1 length byte + up to 31 payload bytes.
    compressor = bytes([13]) + b"AVC Coding\x00\x00\x00" + b"\x00" * 18
    depth = struct.pack(">H", 24)
    pre_defined_3 = struct.pack(">h", -1)

    body = (
        reserved_1 + data_reference_index
        + pre_defined_1 + reserved_2 + pre_defined_2
        + w + h + horiz_reso + vert_reso + reserved_3
        + frame_count + compressor + depth + pre_defined_3
        + _box(b"avcC", avcc)
    )
    return _box(b"avc1", body)


def build_mvhd(timescale: int, duration: int = 0) -> bytes:
    payload = (
        struct.pack(">II", 0, 0)
        + struct.pack(">I", timescale)
        + struct.pack(">I", duration)
        + struct.pack(">I", 0x00010000)          # rate 1.0
        + struct.pack(">H", 0x0100)              # volume 1.0
        + b"\x00" * 10
        + struct.pack(">9I",
                      0x00010000, 0, 0,
                      0, 0x00010000, 0,
                      0, 0, 0x40000000)          # unity matrix
        + b"\x00" * 24
        + struct.pack(">I", 2)                   # next_track_ID
    )
    return _full_box(b"mvhd", 0, 0, payload)


def build_tkhd(track_id: int, width: int, height: int,
               duration: int = 0) -> bytes:
    payload = (
        struct.pack(">II", 0, 0)
        + struct.pack(">I", track_id)
        + struct.pack(">I", 0)
        + struct.pack(">I", duration)
        + b"\x00" * 8
        + struct.pack(">HH", 0, 0)               # layer, alt_group
        + struct.pack(">H", 0)                   # volume
        + struct.pack(">H", 0)
        + struct.pack(">9I",
                      0x00010000, 0, 0,
                      0, 0x00010000, 0,
                      0, 0, 0x40000000)
        + struct.pack(">I", width << 16)
        + struct.pack(">I", height << 16)
    )
    return _full_box(b"tkhd", 0, 7, payload)     # enabled|in_movie|in_preview


def build_mdhd(timescale: int, duration: int = 0) -> bytes:
    payload = (
        struct.pack(">II", 0, 0)
        + struct.pack(">I", timescale)
        + struct.pack(">I", duration)
        + struct.pack(">H", 0x55C4)              # language 'und'
        + struct.pack(">H", 0)
    )
    return _full_box(b"mdhd", 0, 0, payload)


def build_hdlr() -> bytes:
    payload = (
        struct.pack(">I", 0)
        + b"vide"
        + b"\x00" * 12
        + b"VideoHandler\x00"
    )
    return _full_box(b"hdlr", 0, 0, payload)


def build_dinf() -> bytes:
    url = _full_box(b"url ", 0, 1, b"")          # flags=1 => data in same file
    dref = _full_box(b"dref", 0, 0, struct.pack(">I", 1) + url)
    return _box(b"dinf", dref)


def build_vmhd() -> bytes:
    payload = (
        struct.pack(">H", 0)                     # graphicsmode
        + struct.pack(">HHH", 0, 0, 0)           # opcolor
    )
    return _full_box(b"vmhd", 0, 1, payload)


def build_stbl(avc1: bytes) -> bytes:
    stsd = _full_box(b"stsd", 0, 0, struct.pack(">I", 1) + avc1)
    stts = _full_box(b"stts", 0, 0, struct.pack(">I", 0))
    stsc = _full_box(b"stsc", 0, 0, struct.pack(">I", 0))
    stsz = _full_box(b"stsz", 0, 0, struct.pack(">II", 0, 0))
    stco = _full_box(b"stco", 0, 0, struct.pack(">I", 0))
    return _box(b"stbl", stsd + stts + stsc + stsz + stco)


def build_minf(stbl: bytes) -> bytes:
    return _box(b"minf", build_vmhd() + build_dinf() + stbl)


def build_mdia(timescale: int, minf: bytes) -> bytes:
    return _box(b"mdia", build_mdhd(timescale) + build_hdlr() + minf)


def build_trak(track_id: int, width: int, height: int,
               timescale: int, avc1: bytes) -> bytes:
    minf = build_minf(build_stbl(avc1))
    return _box(b"trak",
                build_tkhd(track_id, width, height)
                + build_mdia(timescale, minf))


def build_mvex(track_id: int) -> bytes:
    trex = _full_box(
        b"trex", 0, 0,
        struct.pack(">I", track_id)
        + struct.pack(">I", 1)                   # default_sample_description_index
        + struct.pack(">I", 0)                   # default_sample_duration
        + struct.pack(">I", 0)                   # default_sample_size
        + struct.pack(">I", 0)                   # default_sample_flags
    )
    return _box(b"mvex", trex)


def build_moov(width: int, height: int, timescale: int,
               sps_body: bytes, pps_body: bytes,
               sps_info: SPSInfo) -> bytes:
    """Complete `moov` box for the init segment."""
    avcc = build_avcc(
        sps_body, pps_body,
        sps_info.profile_idc,
        sps_info.constraint_set_flags,
        sps_info.level_idc,
    )
    avc1 = build_avc1(width, height, avcc)
    trak = build_trak(1, width, height, timescale, avc1)
    return _box(b"moov", build_mvhd(timescale) + trak + build_mvex(1))


# ---------------------------------------------------------------------------
# Fragment builders (moof + mdat)
# ---------------------------------------------------------------------------

_TFHD_DEFAULT_BASE_IS_MOOF = 0x020000

_TRUN_DATA_OFFSET = 0x000001
_TRUN_SAMPLE_DUR = 0x000100
_TRUN_SAMPLE_SIZE = 0x000200
_TRUN_SAMPLE_FLAGS = 0x000400

# sample_flags layout (32 bits, big-endian):
#   bits 24-25: sample_depends_on (2 = independent / I-slice, 1 = P/B)
#   bit 16:     sample_is_non_sync_sample (0 = keyframe, 1 = otherwise)
# Everything else zero.
_SAMPLE_FLAG_KEYFRAME = 0x02000000
_SAMPLE_FLAG_NON_KEYFRAME = 0x01010000


def _trun_body(sample_count: int, data_offset: int,
               samples: list[dict]) -> bytes:
    """Serialise the trun body WITHOUT first_sample_flags.

    v3.84.7: dropped first_sample_flags entirely. When both are
    present per ISO 14496-12, first_sample_flags overrides
    sample_flags[0] and different browsers disagree about which value
    wins -- Chrome honours per-sample, Safari honours first-sample. By
    using only per-sample sample_flags we get identical behaviour
    everywhere.
    """
    buf = io.BytesIO()
    buf.write(struct.pack(">I", sample_count))
    buf.write(struct.pack(">i", data_offset))
    for s in samples:
        buf.write(struct.pack(">I", s["duration"]))
        buf.write(struct.pack(">I", len(s["data"])))
        flags = (_SAMPLE_FLAG_KEYFRAME if s["is_keyframe"]
                 else _SAMPLE_FLAG_NON_KEYFRAME)
        buf.write(struct.pack(">I", flags))
    return buf.getvalue()


def build_moof_mdat(sequence_number: int, base_media_decode_time: int,
                    samples: list[dict]) -> tuple[bytes, bytes]:
    """Return `(moof_bytes, mdat_bytes)` for one media fragment.

    Each `samples[i]` is `{"data": bytes, "duration": int,
    "is_keyframe": bool}`. `data` MUST already be in AVCC form:
    each NAL prefixed with its 4-byte big-endian length.
    """
    mdat_payload = b"".join(s["data"] for s in samples)
    mdat = _box(b"mdat", mdat_payload)

    tfhd = _full_box(
        b"tfhd", 0, _TFHD_DEFAULT_BASE_IS_MOOF,
        struct.pack(">I", 1),
    )
    tfdt = _full_box(b"tfdt", 1, 0,
                     struct.pack(">Q", base_media_decode_time))
    mfhd = _full_box(b"mfhd", 0, 0,
                     struct.pack(">I", sequence_number))
    trun_flags = (_TRUN_DATA_OFFSET
                  | _TRUN_SAMPLE_DUR | _TRUN_SAMPLE_SIZE
                  | _TRUN_SAMPLE_FLAGS)

    # First pass with placeholder data_offset to learn moof size.
    trun_pre = _full_box(
        b"trun", 0, trun_flags,
        _trun_body(len(samples), 0, samples),
    )
    traf_pre = _box(b"traf", tfhd + tfdt + trun_pre)
    moof_pre = _box(b"moof", mfhd + traf_pre)

    # Rebuild trun with the real data_offset (= moof size + 8-byte
    # mdat header).
    data_offset = len(moof_pre) + 8
    trun = _full_box(
        b"trun", 0, trun_flags,
        _trun_body(len(samples), data_offset, samples),
    )
    traf = _box(b"traf", tfhd + tfdt + trun)
    moof = _box(b"moof", mfhd + traf)
    return moof, mdat


# ---------------------------------------------------------------------------
# H264 → fMP4 state machine
# ---------------------------------------------------------------------------

# Standard MP4 movie timescale. 90000 divides evenly at 30/25/24/60 fps.
DEFAULT_TIMESCALE = 90_000
DEFAULT_FRAME_DURATION = DEFAULT_TIMESCALE // 30  # 3000 ticks = 33.33 ms


@dataclass
class H264ToFMP4:
    """Consume Annex-B H.264 bytes, produce fMP4 init + media segments.

    Usage:
        mux = H264ToFMP4(on_init=send_init_bytes,
                         on_fragment=send_fragment_bytes)
        mux.feed(chunk_of_h264)
        ...
        mux.flush()  # at pipeline shutdown

    `on_init(bytes)` fires once as soon as SPS+PPS+dimensions are
    known. Payload is `ftyp + moov`.
    `on_fragment(bytes, is_keyframe)` fires per complete access unit
    (typically one video frame). Payload is `moof + mdat`.
    """

    on_init: Callable[[bytes], None]
    on_fragment: Callable[[bytes, bool], None]
    frame_duration: int = DEFAULT_FRAME_DURATION
    timescale: int = DEFAULT_TIMESCALE

    _splitter: AnnexBSplitter = field(default_factory=AnnexBSplitter)
    _sps: bytes | None = None
    _pps: bytes | None = None
    _sps_info: SPSInfo | None = None
    _init_sent: bool = False
    _seq: int = 0
    _decode_time: int = 0
    _pending_nals: list[bytes] = field(default_factory=list)
    _pending_has_vcl: bool = False
    _pending_is_keyframe: bool = False
    # v3.85.4: wall-clock pacing. Android's AVC encoder often emits
    # more temporal-layer frames than the display refresh rate (we've
    # measured 42 fps on a 30 Hz screen because b-frame-like
    # reordering slices land as separate access units). Using a fixed
    # `frame_duration` off DEFAULT_FRAME_DURATION means the MP4
    # timeline runs faster than real time -- MediaSource buffers keep
    # growing and the <video> falls further behind by ~40 % per
    # minute. Measure the wall-clock gap between VCL NALs and use
    # that as the sample duration; playback stays glued to real time.
    _last_frame_wallclock: float = 0.0

    stats_fragments: int = 0
    stats_bytes: int = 0
    stats_keyframes: int = 0

    def reset(self) -> None:
        """Called when screenrecord restarts (new AVC segment). Forgets
        SPS/PPS so the next pair will emit a fresh init segment.
        Deliberately does NOT reset the sequence number or the decode
        clock -- MediaSource hates baseMediaDecodeTime going backwards."""
        self._sps = None
        self._pps = None
        self._sps_info = None
        self._init_sent = False
        self._pending_nals.clear()
        self._pending_has_vcl = False
        self._pending_is_keyframe = False
        # Reset the wall-clock so the first frame in the new segment
        # gets the default duration rather than a huge one.
        self._last_frame_wallclock = 0.0

    def feed(self, chunk: bytes) -> None:
        self._splitter.feed(chunk)
        while True:
            nal = self._splitter.pop()
            if nal is None:
                break
            self._handle_nal(nal)

    def _handle_nal(self, nal: bytes) -> None:
        t = nal_type(nal)
        if t == NAL_SPS:
            self._sps = nal
            try:
                self._sps_info = parse_sps(nal)
            except Exception:
                self._sps_info = None
            self._maybe_emit_init()
            return
        if t == NAL_PPS:
            self._pps = nal
            self._maybe_emit_init()
            return
        if t == NAL_AUD:
            # AUD delimits access units -- flush the previous frame
            # before the AUD's frame starts collecting.
            self._flush_pending_frame()
            return
        if t == NAL_SEI:
            self._pending_nals.append(nal)
            return
        if t in VCL_TYPES:
            # Two VCLs without an AUD in between means the previous
            # one was a complete access unit; flush before appending
            # the new one. (An AUD from screenrecord's bitstream would
            # already have flushed via the NAL_AUD branch above.)
            if self._pending_has_vcl:
                self._flush_pending_frame()
            self._pending_nals.append(nal)
            self._pending_has_vcl = True
            if t == NAL_SLICE_IDR:
                self._pending_is_keyframe = True
            return
        # Unknown / auxiliary NAL: keep it with the current frame.
        self._pending_nals.append(nal)

    def _maybe_emit_init(self) -> None:
        if self._init_sent:
            return
        if not (self._sps and self._pps and self._sps_info):
            return
        # ISO/IEC 14496-15 §5.3.3.1.2: the SPS/PPS payloads inside avcC
        # MUST include their NAL unit header byte (0x67 for SPS,
        # 0x68 for PPS). Slicing `[1:]` here was the source of the
        # "non-existing PPS 0 referenced" decode failures in v3.84.6
        # -- the decoder found no PPS at all and never produced a frame,
        # which manifested as a black <video> in MediaSource because
        # MSE saw a valid init segment but every fragment failed
        # decoding at the first VCL NAL.
        moov = build_moov(
            self._sps_info.width,
            self._sps_info.height,
            self.timescale,
            self._sps,          # full NAL incl. header byte
            self._pps,          # full NAL incl. header byte
            self._sps_info,
        )
        self._init_sent = True
        try:
            self.on_init(build_ftyp() + moov)
        except Exception:
            pass

    def _flush_pending_frame(self) -> None:
        if not self._pending_has_vcl:
            self._pending_nals.clear()
            self._pending_has_vcl = False
            self._pending_is_keyframe = False
            return
        if not self._init_sent:
            # Frame data arrived before SPS+PPS -- discard until an init
            # can be built.
            self._pending_nals.clear()
            self._pending_has_vcl = False
            self._pending_is_keyframe = False
            return

        sample_data = b"".join(
            struct.pack(">I", len(n)) + n for n in self._pending_nals
        )
        # v3.85.4: pace samples so the MP4 timeline advances at the
        # same rate as wall time. Two things get in the way:
        #
        #   * Android's screenrecord emits multiple VCL NALs per
        #     real screen frame (temporal-layer slices) and they
        #     arrive back-to-back within a couple of milliseconds.
        #     Treating each of them as a full frame at
        #     frame_duration = 33.3 ms would run the MP4 timeline
        #     ~40 % faster than reality.
        #
        #   * We can't ask screenrecord for a timestamp per frame --
        #     it doesn't expose one.
        #
        # Compromise: measure the wall-clock gap between successive
        # flushed frames and use that as the sample duration, but
        # clamp it into [3, 100] ms so back-to-back temporal slices
        # get a small (still > 0) duration and a transient stall
        # doesn't inject a giant sample. The average `duration`
        # converges to real time within one second.
        import time as _time
        now = _time.monotonic()
        if self._last_frame_wallclock > 0:
            delta_sec = now - self._last_frame_wallclock
            # After the NAL-aggregation fix above, `delta_sec` is now
            # the gap between REAL screen frames. Clamp
            # [16, 100] ms so a heavy garbage-collection pause doesn't
            # inject a giant sample and a 60 Hz screen doesn't
            # produce durations shorter than one refresh interval.
            delta_sec = max(0.016, min(0.100, delta_sec))
            duration = max(1, int(delta_sec * self.timescale))
        else:
            duration = self.frame_duration
        self._last_frame_wallclock = now
        self._seq += 1
        moof, mdat = build_moof_mdat(
            sequence_number=self._seq,
            base_media_decode_time=self._decode_time,
            samples=[{
                "data": sample_data,
                "duration": duration,
                "is_keyframe": self._pending_is_keyframe,
            }],
        )
        self._decode_time += duration
        fragment = moof + mdat
        self.stats_fragments += 1
        self.stats_bytes += len(fragment)
        was_keyframe = self._pending_is_keyframe
        if was_keyframe:
            self.stats_keyframes += 1

        self._pending_nals.clear()
        self._pending_has_vcl = False
        self._pending_is_keyframe = False
        try:
            self.on_fragment(fragment, was_keyframe)
        except Exception:
            pass

    def flush(self) -> None:
        """Emit any pending frame. Call at pipeline shutdown."""
        # Drain any partial NAL still buffered in the splitter (this
        # only fires at end-of-stream; feed() flushes complete NALs
        # eagerly).
        self._splitter.flush()
        while True:
            nal = self._splitter.pop()
            if nal is None:
                break
            self._handle_nal(nal)
        self._flush_pending_frame()

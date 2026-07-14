"""H.264 Annex-B parser (v3.84.6).

Just the parts of the H.264 spec that the fMP4 muxer needs:

  * `iter_annexb_nals` / `AnnexBSplitter` -- split a byte stream by
    start codes (00 00 00 01 or 00 00 01) into NAL units. The
    incremental `AnnexBSplitter` buffers partial NALs across chunks so
    callers can feed arbitrary-sized reads without worrying about
    alignment.

  * `parse_sps` -- extract width, height, profile_idc, level_idc, and
    constraint_set_flags from a Sequence Parameter Set NAL. Every
    other SPS field is walked but discarded (we still need to walk
    them because their bit widths are variable).

Reference:
  * ITU-T H.264 spec (2019), section 7.3 for SPS syntax and Annex B
    for the byte stream format.
  * ISO/IEC 14496-15 for how these end up in an MP4 avcC box (that
    lives in the sibling `mp4_muxer` module).

The parser deliberately does NOT trust its input:
  * Truncated SPS returns as much as we could parse and stops.
  * Unknown NAL types round-trip through the splitter untouched.
  * Emulation-prevention bytes (0x00 0x00 0x03) are stripped from RBSP.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


# Annex-B start codes are `00 00 00 01` (long) or `00 00 01` (short).
_LONG_START = b"\x00\x00\x00\x01"
_SHORT_START = b"\x00\x00\x01"

# NAL unit types (low 5 bits of the first byte after the start code).
NAL_SLICE_NON_IDR = 1
NAL_SLICE_IDR = 5
NAL_SEI = 6
NAL_SPS = 7
NAL_PPS = 8
NAL_AUD = 9

# VCL (video coding layer) NAL types. A media fragment MUST carry at
# least one of these to be a real access unit.
VCL_TYPES = frozenset({1, 2, 3, 4, 5})


def nal_type(nal: bytes) -> int:
    """Return the `nal_unit_type` field, or -1 for empty input."""
    if not nal:
        return -1
    return nal[0] & 0x1F


def iter_annexb_nals(stream: bytes) -> Iterator[bytes]:
    """Yield each NAL unit (start code stripped) from an Annex-B stream.

    A trailing partial NAL at the end of the buffer (no following start
    code) is returned as the final value so callers can stash it and
    prepend it on the next chunk if they're doing incremental parsing.
    """
    n = len(stream)
    i = 0
    # Skip past leading garbage until we hit a start code.
    while i <= n - 3:
        if i + 4 <= n and stream[i:i + 4] == _LONG_START:
            i += 4
            break
        if stream[i:i + 3] == _SHORT_START:
            i += 3
            break
        i += 1
    else:
        return
    while i < n:
        j = i
        while j <= n - 3:
            # Prefer the 4-byte start code when the preceding byte is 0.
            if stream[j:j + 3] == _SHORT_START:
                nal_end = j
                next_start = j + 3
                break
            if j + 4 <= n and stream[j:j + 4] == _LONG_START:
                nal_end = j
                next_start = j + 4
                break
            j += 1
        else:
            # No more start codes -> yield everything from `i` as the
            # last (possibly complete) NAL.
            yield stream[i:]
            return
        # Trim trailing 0x00 that belongs to a long start code we just
        # found (so the emitted NAL doesn't include that 00).
        while nal_end > i and stream[nal_end - 1] == 0x00:
            nal_end -= 1
        yield stream[i:nal_end]
        i = next_start


class AnnexBSplitter:
    """Incremental Annex-B splitter.

    Feed bytes with `feed(chunk)`, drain complete NAL units with
    `pop()`. Bytes belonging to a partial NAL at the tail are held
    internally until the next feed produces enough data (a new start
    code) to close it.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._nals: list[bytes] = []

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._buf.extend(chunk)
        buf = bytes(self._buf)
        n = len(buf)
        # Locate the LAST start code in the buffer. Everything before
        # it is safe to emit; everything from it onwards might still
        # be growing.
        last_start = -1
        j = n - 3
        while j >= 0:
            if buf[j:j + 3] == _SHORT_START:
                if j > 0 and buf[j - 1] == 0x00:
                    last_start = j - 1
                else:
                    last_start = j
                break
            j -= 1
        if last_start < 0:
            return
        head, tail = buf[:last_start], buf[last_start:]
        # Append a sentinel start code so the last real NAL in `head`
        # closes cleanly.
        for nal in iter_annexb_nals(head + b"\x00\x00\x00\x01"):
            if nal:
                self._nals.append(bytes(nal))
        self._buf = bytearray(tail)

    def pop(self) -> bytes | None:
        if not self._nals:
            return None
        return self._nals.pop(0)

    def has_pending(self) -> bool:
        return bool(self._nals)

    def flush(self) -> None:
        """Force-emit any trailing partial NAL as a complete one.

        Callers hit this at end-of-stream (screenrecord exited, pipe
        closed) so the last frame in the buffer isn't lost. Between
        feeds this must NOT be called -- a valid partial NAL still
        growing across a chunk boundary would be truncated.
        """
        if not self._buf:
            return
        buf = bytes(self._buf)
        # If the buffer starts with a start code, the payload after it
        # is the NAL; otherwise treat the whole buffer as raw NAL bytes.
        if buf.startswith(_LONG_START):
            nal = buf[4:]
        elif buf.startswith(_SHORT_START):
            nal = buf[3:]
        else:
            nal = buf
        if nal:
            self._nals.append(nal)
        self._buf.clear()


# ---------------------------------------------------------------------------
# SPS parsing
# ---------------------------------------------------------------------------

class _RBSP:
    """Bit-level reader over a Raw Byte Sequence Payload.

    Strips emulation prevention (0x00 0x00 0x03 -> 0x00 0x00) on
    construction, then hands out fixed-width bits and exp-Golomb codes.
    """

    def __init__(self, nal_body: bytes) -> None:
        out = bytearray()
        i = 0
        n = len(nal_body)
        while i < n:
            if (i + 2 < n
                    and nal_body[i] == 0
                    and nal_body[i + 1] == 0
                    and nal_body[i + 2] == 0x03):
                out.append(0)
                out.append(0)
                i += 3
                continue
            out.append(nal_body[i])
            i += 1
        self._buf = bytes(out)
        self._pos = 0  # bit position

    def _u1(self) -> int:
        byte = self._buf[self._pos >> 3]
        bit = (byte >> (7 - (self._pos & 7))) & 1
        self._pos += 1
        return bit

    def u(self, n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | self._u1()
        return v

    def ue(self) -> int:
        """unsigned exp-Golomb."""
        zeros = 0
        while self._u1() == 0 and zeros < 32:
            zeros += 1
        return ((1 << zeros) - 1) + self.u(zeros)

    def se(self) -> int:
        """signed exp-Golomb."""
        v = self.ue()
        if v & 1:
            return (v + 1) >> 1
        return -(v >> 1)


@dataclass
class SPSInfo:
    profile_idc: int
    constraint_set_flags: int
    level_idc: int
    width: int
    height: int
    raw: bytes  # the whole SPS NAL incl. type byte; useful for avcC.


def _skip_scaling_list(r: _RBSP, size: int) -> None:
    last_scale = 8
    next_scale = 8
    for _ in range(size):
        if next_scale != 0:
            delta = r.se()
            next_scale = (last_scale + delta + 256) % 256
        if next_scale != 0:
            last_scale = next_scale


def parse_sps(nal: bytes) -> SPSInfo:
    """Extract dimensions + profile info from a Sequence Parameter Set.

    Raises ValueError when the NAL isn't an SPS or the payload is
    truncated. Callers should catch and treat as "wait for the next
    SPS" rather than crashing the mirror session.
    """
    if not nal or nal_type(nal) != NAL_SPS:
        raise ValueError("not an SPS NAL")
    body = nal[1:]
    if len(body) < 3:
        raise ValueError("SPS truncated")
    profile_idc = body[0]
    constraint_flags = body[1]
    level_idc = body[2]
    r = _RBSP(body[3:])
    _seq_parameter_set_id = r.ue()

    chroma_format_idc = 1  # default 4:2:0
    _high_profile_ids = (100, 110, 122, 244, 44, 83, 86,
                         118, 128, 138, 139, 134, 135)
    if profile_idc in _high_profile_ids:
        chroma_format_idc = r.ue()
        if chroma_format_idc == 3:
            r.u(1)  # separate_colour_plane_flag
        r.ue()  # bit_depth_luma_minus8
        r.ue()  # bit_depth_chroma_minus8
        r.u(1)  # qpprime_y_zero_transform_bypass_flag
        if r.u(1):  # seq_scaling_matrix_present_flag
            list_count = 8 if chroma_format_idc != 3 else 12
            for i in range(list_count):
                if r.u(1):
                    _skip_scaling_list(r, 16 if i < 6 else 64)

    r.ue()  # log2_max_frame_num_minus4
    pic_order_cnt_type = r.ue()
    if pic_order_cnt_type == 0:
        r.ue()  # log2_max_pic_order_cnt_lsb_minus4
    elif pic_order_cnt_type == 1:
        r.u(1)  # delta_pic_order_always_zero_flag
        r.se()  # offset_for_non_ref_pic
        r.se()  # offset_for_top_to_bottom_field
        num_ref = r.ue()
        for _ in range(num_ref):
            r.se()
    r.ue()  # num_ref_frames
    r.u(1)  # gaps_in_frame_num_value_allowed_flag
    pic_width_in_mbs_minus1 = r.ue()
    pic_height_in_map_units_minus1 = r.ue()
    frame_mbs_only_flag = r.u(1)
    if not frame_mbs_only_flag:
        r.u(1)  # mb_adaptive_frame_field_flag
    r.u(1)  # direct_8x8_inference_flag

    width = (pic_width_in_mbs_minus1 + 1) * 16
    height = (2 - frame_mbs_only_flag) * (pic_height_in_map_units_minus1 + 1) * 16

    frame_cropping_flag = r.u(1)
    if frame_cropping_flag:
        left = r.ue()
        right = r.ue()
        top = r.ue()
        bottom = r.ue()
        # Assume 4:2:0 / 4:2:2 chroma sub-sampling defaults.
        sub_w = 2 if chroma_format_idc in (1, 2) else 1
        sub_h = 2 if chroma_format_idc == 1 else 1
        crop_unit_x = sub_w
        crop_unit_y = sub_h * (2 - frame_mbs_only_flag)
        width -= crop_unit_x * (left + right)
        height -= crop_unit_y * (top + bottom)

    return SPSInfo(
        profile_idc=profile_idc,
        constraint_set_flags=constraint_flags,
        level_idc=level_idc,
        width=width,
        height=height,
        raw=nal,
    )

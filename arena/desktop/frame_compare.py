"""Whether two captures of the screen show the same picture (#621)."""
from __future__ import annotations

import hashlib
import struct
import zlib
from typing import NamedTuple

# Two captures of an unchanged screen are not always the same bytes: a
# capture tool may stamp the file with the time, or compress it differently.
# So a PNG is compared by its header and its inflated image data, which is
# what the pixels were written from, and not by the file around them. Only
# the standard library is needed for that; Pillow is optional here.
#
# A BMP has nothing but pixels in it, so its bytes are compared. Anything
# else is compared by its bytes too, and the answer says so, because
# "changed" then means less.

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHUNK_OVERHEAD = 12  # length, type, checksum


class Frame(NamedTuple):
    """One capture reduced to what is compared: a digest, and what the digest is of."""

    digest: str
    of: str


def _chunks(encoded: bytes):
    """The (type, data) pairs of a PNG, up to its end marker."""
    at = len(_PNG_SIGNATURE)
    while at + _CHUNK_OVERHEAD <= len(encoded):
        (length,) = struct.unpack(">I", encoded[at:at + 4])
        kind = encoded[at + 4:at + 8]
        if kind == b"IEND":
            return
        yield kind, encoded[at + 8:at + 8 + length]
        at += _CHUNK_OVERHEAD + length


def _png_picture(encoded: bytes) -> str | None:
    """A digest of a PNG's size, pixel format and image data; None if it has no readable picture."""
    digest = hashlib.sha256()
    inflate = zlib.decompressobj()
    seen = set()
    try:
        for kind, data in _chunks(encoded):
            if kind == b"IHDR":
                digest.update(data)
            elif kind == b"IDAT":
                digest.update(inflate.decompress(data))
            else:
                continue
            seen.add(kind)
    except zlib.error:
        return None
    return digest.hexdigest() if seen == {b"IHDR", b"IDAT"} else None


def read_frame(encoded: bytes) -> Frame:
    """Reduce a capture to a digest of its picture, or of its bytes when the picture cannot be told apart."""
    if encoded.startswith(_PNG_SIGNATURE):
        picture = _png_picture(encoded)
        if picture is not None:
            return Frame(picture, "pixels")
    whole = hashlib.sha256(encoded).hexdigest()
    return Frame(whole, "pixels" if encoded.startswith(b"BM") else "bytes")


def compared_as(before: Frame, after: Frame) -> str:
    """`pixels` only when both captures were read as pictures."""
    return "pixels" if before.of == after.of == "pixels" else "bytes"


__all__ = ["Frame", "compared_as", "read_frame"]

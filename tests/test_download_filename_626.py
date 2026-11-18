"""A file whose name would break a header must still download (fuzz regression).

Found by the #258 fuzzing gate on `GET /v1/download`, in the same run that
found the watch-jail 500. The name is not ours -- `gE<U+00D7>\\x06` is a legal
filename on POSIX filesystems -- and it went into `Content-Disposition`
verbatim, so aiohttp refused at serialisation time:

    ValueError: Forbidden control character detected in headers.
                Potential header injection attack.

That raise happens *after* the response has begun, so the client did not get
a 500 either: it got an empty reply, which curl reports as

    curl: (52) Empty reply from server

An unanswerable request is the worst of the three outcomes -- the caller
cannot tell a bad name from a dead bridge.

Two names now, as RFC 6266 §4.3 asks: an ASCII fallback that replaces every
control character and every quote, and `filename*` with the real name
percent-encoded, where CR and LF are escaped by construction.
"""
from __future__ import annotations

import asyncio
import os
from urllib.parse import quote

import pytest

from arena.files.handlers import content_disposition
from tests._live_bridge import auth_header, running_client

TOKEN = "download-name-token-626"

#: Names that cannot go into a header as-is, and what each is for.
HOSTILE = [
    ("gE\u00d7\x06", "control character plus a non-ASCII one"),
    ("na\u00efve report.txt", "non-ASCII only"),
    ('quote"and;semicolon', "the two characters that end or split the name"),
    ("line\r\nbreak", "the injection the header guard exists for"),
]


@pytest.mark.parametrize(("name", "why"), HOSTILE, ids=[w for _, w in HOSTILE])
def test_the_header_cannot_carry_a_control_character(name: str, why: str) -> None:
    header = content_disposition(name)

    assert header.startswith("attachment; filename=\"")
    plain, _, extended = header.partition("; filename*=")
    assert extended.startswith("UTF-8''")
    # The fallback is what a client that ignores `filename*` reads.
    fallback = plain.split('"')[1]
    assert all(32 <= ord(ch) < 127 for ch in fallback), (why, fallback)
    assert '"' not in fallback and ";" not in fallback
    # CR and LF cannot survive the percent-encoding.
    assert "\r" not in extended and "\n" not in extended
    assert "\x06" not in header


def test_an_ordinary_name_is_left_recognisable() -> None:
    """The fix must not turn `report.pdf` into `___________`."""
    assert 'filename="report.pdf"' in content_disposition("report.pdf")


async def _download(root, name: str):
    target = root / name
    target.write_bytes(b"payload")
    async with running_client(root, TOKEN) as client:
        response = await client.get(
            "/v1/download?path=" + quote(str(target)), headers=auth_header(TOKEN),
        )
        return response.status, await response.read(), dict(response.headers)


@pytest.mark.parametrize(("name", "why"), HOSTILE, ids=[w for _, w in HOSTILE])
def test_a_hostile_name_downloads_with_a_status(tmp_path, name: str, why: str) -> None:
    """End to end, because the crash was in the HTTP layer, not in the helper.

    The assertion that matters is that there *is* a status: before the fix the
    response never started, and the client saw an empty reply rather than a
    code it could act on.
    """
    if os.name == "nt" and any(ord(ch) < 32 or ch == '"' for ch in name):
        pytest.skip("Windows does not permit this filename")
    status, body, headers = asyncio.run(_download(tmp_path, name))

    assert status == 200, (why, status, body[:200])
    assert body == b"payload"
    disposition = headers["Content-Disposition"]
    assert disposition.startswith("attachment; filename=")
    assert "\r" not in disposition and "\n" not in disposition

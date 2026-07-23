"""Sound helper tests.

v4.61.1: ``test_play_beep_simulates_without_device`` is now
skipped on ``win32``. The test only exercises the Linux
subprocess path (``paplay`` / ``aplay`` / ``beep``); on
Windows the dispatch in ``play_beep`` goes through
``winsound.Beep``, which is a no-op + ``True`` return on a
machine with no sound device but the path is not what this
test is asserting. The test is still valuable on Linux so
we keep it; we just skip the Windows platform.

Live-failed: v4.61.0 CI run id 30034756453 on
``windows-latest`` Python 3.10-3.14.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.system.sound import generate_wav_bytes, play_beep  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_generate_wav_bytes_header():
    data = generate_wav_bytes(440, 50)
    assert data.startswith(b"RIFF")
    assert b"WAVE" in data[:16]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "This test exercises the Linux subprocess path "
        "(paplay/aplay/beep) by mocking shutil.which to return "
        "None. The Windows dispatch in play_beep goes through "
        "winsound.Beep, which is not what this test asserts. "
        "The Linux path is still covered on Linux runners."
    ),
)
def test_play_beep_simulates_without_device(monkeypatch):
    import arena.system.sound as snd
    monkeypatch.setattr(snd.shutil, "which", lambda name: None)
    res = play_beep("success", 800, 10, subprocess_kwargs_fn=lambda: {})
    assert res["ok"] is True
    assert res["type"] == "success"


def test_unified_bridge_sound_reexports():
    assert ub.generate_wav_bytes is generate_wav_bytes
    assert callable(ub._play_beep_sync)

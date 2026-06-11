"""Sound helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.system.sound import generate_wav_bytes, play_beep  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_generate_wav_bytes_header():
    data = generate_wav_bytes(440, 50)
    assert data.startswith(b"RIFF")
    assert b"WAVE" in data[:16]


def test_play_beep_simulates_without_device(monkeypatch):
    import arena.system.sound as snd
    monkeypatch.setattr(snd.shutil, "which", lambda name: None)
    res = play_beep("success", 800, 10, subprocess_kwargs_fn=lambda: {})
    assert res["ok"] is True
    assert res["type"] == "success"


def test_unified_bridge_sound_reexports():
    assert ub.generate_wav_bytes is generate_wav_bytes
    assert callable(ub._play_beep_sync)

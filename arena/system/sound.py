"""Sound/beep notification helpers."""
from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Any, Callable


def winsound_melody() -> None:
    import winsound
    for freq, dur in [(523, 150), (659, 150), (784, 150), (1047, 300)]:
        winsound.Beep(freq, dur)


def generate_wav_bytes(freq: int, duration_ms: int, volume: float = 0.5) -> bytes:
    sample_rate = 22050
    num_samples = int(sample_rate * duration_ms / 1000)
    fade_samples = min(int(sample_rate * 0.02), num_samples // 4)
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        val = math.sin(2 * math.pi * freq * t) * volume * 32767
        if i < fade_samples:
            val *= i / fade_samples
        elif i > num_samples - fade_samples:
            val *= (num_samples - i) / fade_samples
        samples.append(int(val))
    data_size = num_samples * 2
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI', b'RIFF', 36 + data_size, b'WAVE', b'fmt ', 16,
        1, 1, sample_rate, sample_rate * 2, 2, 16, b'data', data_size,
    )
    return header + b''.join(struct.pack('<h', max(-32768, min(32767, sample))) for sample in samples)


def _combine_wav_notes(notes: list[tuple[int, int]]) -> bytes:
    wav_parts = [generate_wav_bytes(freq, dur) for freq, dur in notes]
    silence = generate_wav_bytes(1, 50, volume=0.0)
    combined = wav_parts[0]
    for part in wav_parts[1:]:
        combined = combined[:-44]
        combined += silence[44:]
        combined += part[44:]
    total_data_size = len(combined) - 8
    combined = combined[:4] + struct.pack('<I', total_data_size) + combined[8:]
    data_chunk_size = len(combined) - 44
    return combined[:40] + struct.pack('<I', data_chunk_size) + combined[44:]


def linux_play_beep(beep_type: str, freq: int, dur: int, *, subprocess_kwargs_fn: Callable[[], dict] = lambda: {}) -> dict[str, Any]:
    melodies = {
        "success": [(523, 120), (659, 120), (784, 200)],
        "warning": [(440, 200), (380, 300)],
        "error": [(330, 200), (262, 400)],
        "attention": [(880, 80), (880, 80), (880, 200)],
        "melody": [(523, 150), (659, 150), (784, 150), (1047, 300)],
    }
    notes = melodies.get(beep_type, [(freq, dur)])

    for player, args in [("paplay", []), ("aplay", ["-q"] )]:
        if shutil.which(player):
            try:
                combined = _combine_wav_notes(notes)
                tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                tmp.write(combined)
                tmp.close()
                try:
                    subprocess.run([player, *args, tmp.name], timeout=3, **subprocess_kwargs_fn())
                    return {"ok": True, "type": beep_type, "method": player}
                finally:
                    try:
                        os.unlink(tmp.name)
                    except Exception:
                        pass
            except Exception:
                pass

    if shutil.which("beep"):
        try:
            for note_freq, note_dur in notes:
                subprocess.run(["beep", "-f", str(note_freq), "-l", str(note_dur)], timeout=3)
            return {"ok": True, "type": beep_type, "method": "beep"}
        except Exception:
            pass
    return {"ok": True, "type": beep_type, "note": "no sound device, simulated"}


def play_beep(beep_type: str, freq: int, dur: int, *, subprocess_kwargs_fn: Callable[[], dict] = lambda: {}) -> dict[str, Any]:
    if sys.platform == "win32":
        try:
            import winsound
            if beep_type == "melody":
                winsound_melody()
            else:
                winsound.Beep(freq, dur)
            return {"ok": True, "type": beep_type, "frequency": freq, "duration": dur}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return linux_play_beep(beep_type, freq, dur, subprocess_kwargs_fn=subprocess_kwargs_fn)

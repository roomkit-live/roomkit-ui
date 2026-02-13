"""Notification sounds for session start/stop."""

from __future__ import annotations

import io
import logging
import math
import struct
import tempfile
import wave
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 44100
_cache_dir: Path | None = None


def _ensure_cache_dir() -> Path:
    global _cache_dir  # noqa: PLW0603
    if _cache_dir is None:
        _cache_dir = Path(tempfile.mkdtemp(prefix="roomkit_sounds_"))
    return _cache_dir


def _generate_tone(
    freq: float,
    duration: float,
    volume: float = 0.3,
    fade_ms: float = 15.0,
) -> list[int]:
    """Generate a sine wave tone as 16-bit PCM samples."""
    n_samples = int(_SAMPLE_RATE * duration)
    fade_samples = int(_SAMPLE_RATE * fade_ms / 1000.0)
    samples: list[int] = []
    for i in range(n_samples):
        t = i / _SAMPLE_RATE
        val = math.sin(2.0 * math.pi * freq * t) * volume
        # Fade in/out to avoid clicks
        if i < fade_samples:
            val *= i / fade_samples
        elif i > n_samples - fade_samples:
            val *= (n_samples - i) / fade_samples
        samples.append(int(val * 32767))
    return samples


def _write_wav(samples: list[int], path: Path) -> None:
    """Write 16-bit mono PCM samples to a WAV file."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    path.write_bytes(buf.getvalue())


def _generate_start_sound() -> Path:
    """Two rising tones — a gentle 'ding-ding'."""
    path = _ensure_cache_dir() / "session_start.wav"
    if path.exists():
        return path
    # C5 (523 Hz) then E5 (659 Hz), each 120ms with a 30ms gap
    tone1 = _generate_tone(523.25, 0.12, volume=0.25)
    gap = [0] * int(_SAMPLE_RATE * 0.03)
    tone2 = _generate_tone(659.25, 0.15, volume=0.25)
    _write_wav(tone1 + gap + tone2, path)
    return path


def _generate_stop_sound() -> Path:
    """Single descending tone — a gentle 'dong'."""
    path = _ensure_cache_dir() / "session_stop.wav"
    if path.exists():
        return path
    tone = _generate_tone(440.0, 0.15, volume=0.20)
    _write_wav(tone, path)
    return path


# Module-level QSoundEffect instances (lazily created).
_start_effect: QSoundEffect | None = None
_stop_effect: QSoundEffect | None = None


def play_session_start() -> None:
    """Play the session-start notification sound."""
    global _start_effect  # noqa: PLW0603
    try:
        if _start_effect is None:
            _start_effect = QSoundEffect()
            _start_effect.setSource(QUrl.fromLocalFile(str(_generate_start_sound())))
            _start_effect.setVolume(0.5)
        _start_effect.play()
    except Exception:
        logger.debug("Could not play start sound", exc_info=True)


def play_session_stop() -> None:
    """Play the session-stop notification sound."""
    global _stop_effect  # noqa: PLW0603
    try:
        if _stop_effect is None:
            _stop_effect = QSoundEffect()
            _stop_effect.setSource(QUrl.fromLocalFile(str(_generate_stop_sound())))
            _stop_effect.setVolume(0.4)
        _stop_effect.play()
    except Exception:
        logger.debug("Could not play stop sound", exc_info=True)

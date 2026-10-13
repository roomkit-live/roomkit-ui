"""Notification sounds for session start/stop and dictation.

They play through sounddevice (PortAudio), never QtMultimedia's QSoundEffect:
its play() holds the GIL down into CoreAudio, which waits for the output
device's lock while a session's PortAudio callback holds that lock and waits
for the GIL — the session-start sound froze the app as a Live session opened.
sounddevice calls into PortAudio with the GIL released.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 44100

# name → its samples, generated on first use.
_tones: dict[str, Any] = {}


def _tone(freq: float, duration: float, volume: float, fade_ms: float = 15.0) -> Any:
    """A sine tone as float32 samples, faded in and out to avoid clicks."""
    import numpy as np

    n_samples = int(_SAMPLE_RATE * duration)
    fade = int(_SAMPLE_RATE * fade_ms / 1000.0)
    t = np.arange(n_samples, dtype=np.float32) / _SAMPLE_RATE
    samples = np.sin(2.0 * np.pi * freq * t) * volume
    ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    samples[:fade] *= ramp
    samples[-fade:] *= ramp[::-1]
    return samples.astype(np.float32)


def _silence(duration: float) -> Any:
    import numpy as np

    return np.zeros(int(_SAMPLE_RATE * duration), dtype=np.float32)


def _samples(name: str) -> Any:
    samples = _tones.get(name)
    if samples is None:
        import numpy as np

        if name == "session_start":
            # Two rising tones — a gentle "ding-ding": C5 then E5.
            samples = np.concatenate(
                [_tone(523.25, 0.12, 0.125), _silence(0.03), _tone(659.25, 0.15, 0.125)]
            )
        elif name == "session_stop":
            samples = _tone(440.0, 0.15, 0.08)  # a gentle "dong"
        elif name == "dictation_start":
            samples = _tone(783.99, 0.10, 0.075)  # a light "pip"
        else:
            samples = _tone(587.33, 0.10, 0.048)  # a softer, lower "pip"
        _tones[name] = samples
    return samples


def _play(name: str) -> None:
    try:
        import sounddevice as sd

        sd.play(_samples(name), _SAMPLE_RATE)
    except Exception:
        logger.debug("Could not play the %s sound", name, exc_info=True)


def play_dictation_start() -> None:
    """Play the dictation-start notification sound."""
    _play("dictation_start")


def play_dictation_stop() -> None:
    """Play the dictation-stop notification sound."""
    _play("dictation_stop")


def play_session_start() -> None:
    """Play the session-start notification sound."""
    _play("session_start")


def play_session_stop() -> None:
    """Play the session-stop notification sound."""
    _play("session_stop")


def cleanup() -> None:
    """Stop a sound still playing as the app quits."""
    if not _tones:
        return  # none ever played: nothing to stop, and no PortAudio to load
    try:
        import sounddevice as sd

        sd.stop()
    except Exception:
        pass

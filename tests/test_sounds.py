"""Notification sounds play through sounddevice, never QSoundEffect, whose
play() held the GIL into CoreAudio while a session's PortAudio callback waited
for it: the app froze as a Live session opened."""

import sys
import types

import numpy as np
import pytest

from roomkit_ui import sounds


@pytest.fixture
def played(monkeypatch):
    calls: list[tuple[np.ndarray, int]] = []
    fake = types.SimpleNamespace(
        play=lambda samples, rate: calls.append((samples, rate)), stop=lambda: None
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    monkeypatch.setattr(sounds, "_tones", {})
    return calls


@pytest.mark.parametrize(
    "play",
    [
        sounds.play_session_start,
        sounds.play_session_stop,
        sounds.play_dictation_start,
        sounds.play_dictation_stop,
    ],
)
def test_each_sound_is_a_short_quiet_tone_through_portaudio(played, play):
    play()

    ((samples, rate),) = played
    assert rate == 44100 and samples.dtype == np.float32
    assert 0.05 < len(samples) / rate < 0.5
    assert 0 < np.abs(samples).max() <= 0.125
    assert abs(samples[0]) < 0.01 and abs(samples[-1]) < 0.01  # faded: no click


def test_a_sound_that_cannot_play_is_skipped(monkeypatch):
    def broken(_samples, _rate):
        raise RuntimeError("no output device")

    monkeypatch.setitem(
        sys.modules, "sounddevice", types.SimpleNamespace(play=broken, stop=lambda: None)
    )

    sounds.play_session_start()  # no exception: a sound is a nicety

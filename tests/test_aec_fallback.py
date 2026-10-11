"""An echo canceller that cannot load falls back to half-duplex, visibly.

aec_audio_processing loads its native library with ctypes and raises OSError
when it is missing (a frozen bundle without it) — not ImportError. Uncaught,
every session with the default aec_mode="webrtc" ended in ERROR.
"""

import pytest
from roomkit.voice.pipeline.aec import webrtc

from roomkit_ui.engine_audio import build_audio_processing, notify_missing_aec


def _broken_library():
    raise OSError("Error loading webrtc library at …/libwebrtc-audio-processing-2.so")


def test_a_native_library_that_fails_to_load_leaves_no_aec(monkeypatch):
    monkeypatch.setattr(webrtc, "_import_webrtc", _broken_library)

    aec, denoiser = build_audio_processing("webrtc", "none", 24000, 480)

    assert aec is None
    assert denoiser is None


def test_a_missing_aec_is_said_in_the_chat():
    notices: list[str] = []

    notify_missing_aec("webrtc", None, notices.append)

    assert len(notices) == 1
    assert "echo cancellation" in notices[0]
    assert "muted while the assistant speaks" in notices[0]


@pytest.mark.parametrize("mode, aec", [("none", None), ("webrtc", object())])
def test_no_notice_when_nothing_was_lost(mode, aec):
    notices: list[str] = []

    notify_missing_aec(mode, aec, notices.append)

    assert notices == []

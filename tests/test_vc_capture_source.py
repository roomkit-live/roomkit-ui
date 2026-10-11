"""A voice-channel session opened by the wake word hears the whole request.

Realtime sessions subscribed to the shared microphone and replayed it from
the wake word's mark; the voice channel opened its own device and dropped
the mark, so the words said while the session was being built were lost.
And the shared source was opened at the realtime provider's rate, which a
voice-channel session (16 kHz) could not use anyway.

These run a real LocalAudioBackend over roomkit's MockCaptureSource: no
audio device is opened.
"""

import asyncio

import pytest
from roomkit.voice.capture.mock import MockCaptureSource

from roomkit_ui.engine import Engine
from roomkit_ui.engine_audio import session_input_rate


class _Voice:
    def bind_session(self, session, room_id, binding):
        pass


@pytest.fixture
def engine(qapp):
    return Engine()


def _heard(backend) -> list[bytes]:
    heard: list[bytes] = []
    backend.on_audio_received(lambda _session, frame: heard.append(frame.data))
    return heard


async def test_the_words_said_before_the_session_reach_it(engine):
    source = MockCaptureSource(sample_rate=16000)
    engine.set_capture_source(source)
    source.feed_blocks(2, fill=100)  # before the wake word: not replayed
    engine._capture_since = source.mark()
    request = source.feed_blocks(4, fill=1)  # said while the session is built

    backend = engine._build_vc_backend({}, aec=None, output_sample_rate=24000)
    heard = _heard(backend)
    await engine._listen(backend, _Voice(), None)
    live = source.feed_blocks(1, fill=50)
    await asyncio.sleep(0)

    assert heard == request + live


async def test_a_source_at_another_rate_is_not_used(engine):
    source = MockCaptureSource(sample_rate=24000)
    engine.set_capture_source(source)

    backend = engine._build_vc_backend({}, aec=None, output_sample_rate=24000)

    assert backend._source is None  # its own device, as realtime does on a mismatch


@pytest.mark.parametrize(
    "settings, rate",
    [
        ({"conversation_mode": "voice_channel", "provider": "gemini"}, 16000),
        ({"conversation_mode": "realtime", "provider": "gemini"}, 24000),
        ({"conversation_mode": "realtime", "provider": "elevenlabs"}, 16000),
        ({}, 24000),
    ],
)
def test_the_shared_source_is_opened_at_the_rate_the_session_needs(settings, rate):
    assert session_input_rate(settings) == rate

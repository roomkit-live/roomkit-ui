"""The mute button silences the microphone in both modes, from any state.

set_mic_muted only reached the realtime transport: in voice-channel mode
the VU meter dropped to zero while the speech still reached STT and the AI
answered. And a mute pressed while connecting had no session to reach and
was never applied again — the session started with the mic open.

These run a real LocalAudioBackend over roomkit's MockCaptureSource, so no
audio device is opened: frames fed to the source go through the backend's
own mute check.
"""

import asyncio
from types import SimpleNamespace

import pytest
from roomkit.voice.backends.local import LocalAudioBackend
from roomkit.voice.base import VoiceSession
from roomkit.voice.capture.mock import MockCaptureSource

from roomkit_ui.engine import Engine


@pytest.fixture
def mic():
    source = MockCaptureSource(sample_rate=16000)
    backend = LocalAudioBackend(output_sample_rate=16000, source=source)
    heard: list[bytes] = []
    backend.on_audio_received(lambda _session, frame: heard.append(frame.data))
    return SimpleNamespace(source=source, backend=backend, heard=heard)


async def _speak(mic, blocks=3) -> int:
    before = len(mic.heard)
    mic.source.feed_blocks(blocks, fill=1)
    await asyncio.sleep(0)  # frames reach the callback through the loop
    return len(mic.heard) - before


class _Voice:
    def bind_session(self, session, room_id, binding):
        pass


async def test_mute_silences_a_voice_channel_session(qapp, mic):
    engine = Engine()
    engine._backend = mic.backend
    await engine._listen(mic.backend, _Voice(), None)
    assert await _speak(mic) == 3

    engine.set_mic_muted(True)
    assert await _speak(mic) == 0

    engine.set_mic_muted(False)
    assert await _speak(mic) == 3


async def test_a_mute_pressed_while_connecting_holds_the_voice_channel_session(qapp, mic):
    engine = Engine()
    engine._backend = mic.backend
    engine.set_mic_muted(True)  # no session yet

    await engine._listen(mic.backend, _Voice(), None)

    assert await _speak(mic) == 0


async def test_a_mute_pressed_while_connecting_holds_the_realtime_session(qapp, mic):
    engine = Engine()
    engine._transport = mic.backend
    mic.backend.on_session_ready(engine._apply_mic_mute)  # as _start_realtime wires it
    engine.set_mic_muted(True)  # no session yet: the channel creates it later

    session = VoiceSession(id="rt", room_id="main", participant_id="u", channel_id="voice")
    await mic.backend.start_listening(session)  # what accept() runs once connected

    assert await _speak(mic) == 0

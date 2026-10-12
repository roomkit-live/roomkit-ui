"""One microphone session per voice channel: the app's own.

roomkit's LocalAudioBackend declares ``auto_connect``: attaching its
VoiceChannel to a room joins a session and starts the mic.  The app then
opened its own (``_listen``: the wake word's replay mark, the user's mute
before the first frame), so a Voice Channel session ran two captures, two
STT streams and two playbacks: every sentence was heard, answered and spoken
twice.  Dictation did the same.  The app's local backends no longer
auto-connect.

These run real LocalAudioBackends over roomkit's MockCaptureSource: no audio
device is opened.
"""

import pytest
from roomkit import RoomKit, VoiceChannel
from roomkit.voice.backends.local import LocalAudioBackend
from roomkit.voice.capture.mock import MockCaptureSource
from roomkit.voice.pipeline import AudioPipelineConfig
from roomkit.voice.stt.mock import MockSTTProvider

from roomkit_ui.engine import Engine
from roomkit_ui.engine_audio import local_audio_backend


@pytest.fixture
def engine(qapp):
    eng = Engine()
    eng.set_capture_source(MockCaptureSource(sample_rate=16000))
    return eng


async def _sessions_after_start(engine: Engine, backend) -> list:
    """What the app's start leaves on the backend: attach, then _listen."""
    voice = VoiceChannel(
        "voice", stt=MockSTTProvider(), backend=backend, pipeline=AudioPipelineConfig()
    )
    kit = RoomKit()
    kit.register_channel(voice)
    await kit.create_room(room_id=engine._room_id)
    try:
        binding = await kit.attach_channel(engine._room_id, "voice")
        await engine._listen(backend, voice, binding)
        return backend.list_sessions(engine._room_id)
    finally:
        await kit.close()


async def test_a_voice_channel_session_opens_one_mic_session(engine):
    backend = engine._build_vc_backend({}, aec=None, output_sample_rate=24000)

    sessions = await _sessions_after_start(engine, backend)

    assert [s.participant_id for s in sessions] == ["local-user"]


async def test_a_plain_local_backend_would_open_two(engine):
    # Why the app's backends opt out: the bug, as roomkit's default does it.
    plain = LocalAudioBackend(input_sample_rate=16000, source=engine._capture_source)

    sessions = await _sessions_after_start(engine, plain)

    assert len(sessions) == 2


def test_the_apps_local_backends_never_join_on_their_own():
    assert not local_audio_backend(input_sample_rate=16000).auto_connect

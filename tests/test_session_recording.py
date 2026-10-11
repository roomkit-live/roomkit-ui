"""Session recording writes playable WAV files.

roomkit's WavFileRecorder refuses to start unless the RecordingConfig names
a cipher or declares storage_encrypted_at_rest. The app set neither, so the
pipeline logged "Failed to start recording" and every session with recording
enabled recorded nothing.
"""

import wave

from roomkit.voice.audio_frame import AudioFrame
from roomkit.voice.base import VoiceSession
from roomkit.voice.pipeline.config import AudioPipelineConfig
from roomkit.voice.pipeline.engine import AudioPipeline

from roomkit_ui.engine_audio import build_recorder


async def test_a_session_with_recording_enabled_writes_a_wav(tmp_path):
    recorder, config = build_recorder(
        {
            "recording_enabled": True,
            "recording_output_dir": str(tmp_path),
            "recording_mode": "inbound_only",
            "recording_channels": "mixed",
        }
    )
    pipeline = AudioPipeline(AudioPipelineConfig(recorder=recorder, recording_config=config))
    session = VoiceSession(id="s1", room_id="main", participant_id="u", channel_id="voice")

    pipeline.on_session_active(session)
    for _ in range(5):
        pipeline.process_inbound(session, AudioFrame(data=b"\x01\x00" * 320, sample_rate=16000))
    pipeline.on_session_ended(session)

    files = list(tmp_path.glob("*.wav"))
    assert len(files) == 1
    with wave.open(str(files[0])) as wav:  # plain WAV, playable as is
        assert wav.getframerate() == 16000
        assert wav.getnframes() == 5 * 320

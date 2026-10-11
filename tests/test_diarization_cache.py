"""A second session reuses the cached diarization provider without failing.

roomkit keys diarization state by stream: ``reset(stream)`` needs the stream
id, and the pipeline calls it when a session's stream ends. The cache-hit path
still called ``reset()`` with no argument, so every second session with
diarization — the first to hit the cache — died on a TypeError (state ERROR).
"""

from types import SimpleNamespace

from roomkit.voice.pipeline.diarization.mock import MockDiarizationProvider

from roomkit_ui import model_manager, speaker_manager
from roomkit_ui.engine_audio import setup_diarization


class _Enrollable(MockDiarizationProvider):
    """roomkit's mock, with the enrollment calls the engine makes."""

    def __init__(self):
        super().__init__()
        self.cleared = 0
        self.enrolled: list[str] = []

    def clear_speakers(self):
        self.cleared += 1
        self.enrolled.clear()

    def register_speaker(self, name, embeddings):
        self.enrolled.append(name)
        return True


def _engine(cached):
    return SimpleNamespace(
        _get_cached=lambda kind, key: cached,
        _set_cached=lambda kind, key, value: None,
        loading_status=SimpleNamespace(emit=lambda _text: None),
        _diarization=None,
        _primary_speaker_mode=False,
        _primary_speaker_name="",
    )


def test_cached_provider_is_reused_with_a_fresh_enrollment(monkeypatch):
    monkeypatch.setattr(model_manager, "is_speaker_model_downloaded", lambda _id: True)
    profile = speaker_manager.SpeakerProfile(name="Alice", embeddings=[[0.1, 0.2]])
    monkeypatch.setattr(speaker_manager, "load_speakers", lambda: [profile])
    cached = _Enrollable()
    cached.enrolled.append("Bob")  # enrolled by the previous session, since deleted
    engine = _engine(cached)
    settings = {"diarization_enabled": True, "diarization_model": "speaker-model"}

    result = setup_diarization(engine, settings, vad_available=True, inference_device="cpu")

    assert result is cached
    assert engine._diarization is cached
    assert cached.cleared == 1
    assert cached.enrolled == ["Alice"]

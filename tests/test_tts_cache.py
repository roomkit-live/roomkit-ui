"""The cached TTS is rebuilt when the voice it clones changes.

Qwen3-TTS and NeuTTS are built from a reference recording and its
transcript, but the cache key only held (provider, model, device): a new
reference voice kept the old one until the app restarted.
"""

import os

import pytest

from roomkit_ui import engine_vc
from roomkit_ui.engine import Engine


@pytest.fixture
def engine(qapp, monkeypatch):
    built: list[object] = []

    def create(name, settings):
        tts = object()
        built.append(tts)
        return tts, 24000

    monkeypatch.setattr(engine_vc, "create_tts_provider", create)
    eng = Engine()
    eng.built = built
    return eng


def _settings(ref_audio, ref_text="Hello, this is my voice."):
    return {
        "vc_tts_provider": "qwen3",
        "vc_tts_ref_audio": str(ref_audio),
        "vc_tts_ref_text": ref_text,
    }


async def test_same_reference_voice_reuses_the_cached_tts(engine, tmp_path):
    ref = tmp_path / "me.wav"
    ref.write_bytes(b"RIFF")

    first, _ = await engine._build_tts(_settings(ref), "cpu")
    second, _ = await engine._build_tts(_settings(ref), "cpu")

    assert first is second
    assert len(engine.built) == 1


async def test_another_reference_file_rebuilds_the_tts(engine, tmp_path):
    (tmp_path / "me.wav").write_bytes(b"RIFF")
    (tmp_path / "other.wav").write_bytes(b"RIFF")

    first, _ = await engine._build_tts(_settings(tmp_path / "me.wav"), "cpu")
    second, _ = await engine._build_tts(_settings(tmp_path / "other.wav"), "cpu")

    assert first is not second


async def test_a_reference_recorded_again_in_place_rebuilds_the_tts(engine, tmp_path):
    ref = tmp_path / "me.wav"
    ref.write_bytes(b"RIFF")
    first, _ = await engine._build_tts(_settings(ref), "cpu")

    ref.write_bytes(b"RIFF again")
    stat = ref.stat()
    os.utime(ref, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    second, _ = await engine._build_tts(_settings(ref), "cpu")

    assert first is not second


async def test_a_new_transcript_rebuilds_the_tts(engine, tmp_path):
    ref = tmp_path / "me.wav"
    ref.write_bytes(b"RIFF")

    first, _ = await engine._build_tts(_settings(ref, "First words."), "cpu")
    second, _ = await engine._build_tts(_settings(ref, "Other words."), "cpu")

    assert first is not second

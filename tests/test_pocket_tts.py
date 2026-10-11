"""Pocket TTS: built from the settings, cached across sessions like the other local voices."""

import os

import pytest
import shiboken6

from roomkit_ui import engine_vc
from roomkit_ui.engine import Engine
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.tts import is_cached_tts, pocket
from roomkit_ui.widgets.settings.ai_page import VC_TTS_PROVIDERS, _AIPage

# -- factory -------------------------------------------------------------------


def test_defaults_are_roomkits_english_model_and_voice():
    tts, rate = pocket.create({})

    assert rate == 24000
    assert tts._config.language == "english"
    assert tts._config.voices == {"default": "alba"}
    assert tts._config.device == "cpu"


def test_french_defaults_to_the_french_voice():
    tts, _ = pocket.create({"vc_pocket_language": "french_24l"})

    assert tts._config.language == "french_24l"
    assert tts._config.voices == {"default": "estelle"}


def test_by_default_pocket_speaks_the_speech_recognition_language():
    tts, _ = pocket.create({"stt_language": "fr"})

    assert tts._config.language == "french"
    assert tts._config.voices == {"default": "estelle"}


def test_a_chosen_language_wins_over_the_speech_recognition_one():
    tts, _ = pocket.create({"stt_language": "fr", "vc_pocket_language": "german"})

    assert tts._config.language == "german"


def test_a_language_pocket_has_no_model_for_speaks_english():
    for stt_language in ("ja", ""):  # Japanese, and STT on auto-detect
        tts, _ = pocket.create({"stt_language": stt_language})
        assert tts._config.language == "english"


def test_a_clip_is_cloned_and_cuda_is_followed(tmp_path):
    clip = tmp_path / "me.wav"
    clip.write_bytes(b"RIFF")

    tts, _ = pocket.create({"vc_pocket_voice": str(clip), "inference_device": "cuda"})

    assert tts._config.voices == {"default": str(clip)}
    assert tts._config.device == "cuda"


def test_coreml_falls_back_to_the_cpu():
    tts, _ = pocket.create({"inference_device": "coreml"})
    assert tts._config.device == "cpu"


# -- engine cache ----------------------------------------------------------------


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


def _settings(**overrides):
    return {"vc_tts_provider": "pocket", **overrides}


def test_pocket_is_a_cached_local_voice():
    assert is_cached_tts("pocket")
    assert not is_cached_tts("elevenlabs")


async def test_the_same_settings_reuse_the_cached_pocket_tts(engine):
    first, _ = await engine._build_tts(_settings(vc_pocket_language="french"), "cpu")
    second, _ = await engine._build_tts(_settings(vc_pocket_language="french"), "cpu")

    assert first is second
    assert len(engine.built) == 1


async def test_another_language_or_voice_rebuilds_it(engine):
    first, _ = await engine._build_tts(_settings(vc_pocket_language="french"), "cpu")
    second, _ = await engine._build_tts(_settings(vc_pocket_language="german"), "cpu")
    third, _ = await engine._build_tts(
        _settings(vc_pocket_language="german", vc_pocket_voice="marius"), "cpu"
    )

    assert len({id(first), id(second), id(third)}) == 3


async def test_a_clip_recorded_again_in_place_rebuilds_it(engine, tmp_path):
    clip = tmp_path / "me.wav"
    clip.write_bytes(b"RIFF")
    first, _ = await engine._build_tts(_settings(vc_pocket_voice=str(clip)), "cpu")

    stat = clip.stat()
    os.utime(clip, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    second, _ = await engine._build_tts(_settings(vc_pocket_voice=str(clip)), "cpu")

    assert first is not second


# -- settings page ---------------------------------------------------------------


def test_the_settings_page_offers_pocket_with_its_fields(qapp):
    page = _AIPage(
        {
            **_DEFAULTS,
            "vc_tts_provider": "pocket",
            "vc_pocket_language": "french",
            "vc_pocket_voice": "estelle",
        }
    )
    try:
        local = page._local
        assert ("Pocket TTS (local, voice clone)", "pocket") in VC_TTS_PROVIDERS
        assert not local.vc_pocket_voice.isHidden()
        assert local.vc_tts_ref_text.isHidden()  # Qwen3/NeuTTS's transcript
        out = page.get_settings()
        assert out["vc_tts_provider"] == "pocket"
        assert out["vc_pocket_language"] == "french"
        assert out["vc_pocket_voice"] == "estelle"
    finally:
        shiboken6.delete(page)

"""Vui: built from the settings, told the dialogue with the user's voice, English only."""

import os
from unittest.mock import AsyncMock

import pytest
import shiboken6
from roomkit.voice.tts import vui as roomkit_vui

from roomkit_ui import audio_tags, components, engine_vc, features
from roomkit_ui.engine import Engine
from roomkit_ui.engine_vc_helpers import build_tts_filter, tts_context
from roomkit_ui.features import Feature
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.tts import is_cached_tts, vui
from roomkit_ui.widgets.settings.voice_setup import VC_TTS_PROVIDERS, VoiceSetup

_VUI = {"vc_tts_provider": "vui"}


def test_the_app_lists_roomkits_voices_and_tags():
    assert vui.PRESETS == roomkit_vui.PRESET_VOICES
    # In another order: the prompt's example opens with the list's laugh.
    assert set(audio_tags.closed_tags(_VUI)) == set(roomkit_vui.VUI_TAGS)


# -- factory -------------------------------------------------------------------


def test_the_default_voice_is_maeve_at_24_khz():
    tts, rate = vui.create({})

    assert rate == 24000
    assert tts._config.voices == {"maeve": roomkit_vui.VuiVoice("maeve")}


def test_a_clip_is_cloned_with_its_transcript(tmp_path):
    clip = tmp_path / "me.wav"
    clip.write_bytes(b"RIFF")

    tts, _ = vui.create(
        {"vc_vui_voice": vui.CLONE, "vc_tts_ref_audio": str(clip), "vc_tts_ref_text": "Hi."}
    )

    assert tts._config.voices == {
        vui.CLONE: roomkit_vui.VuiVoice(ref_audio=str(clip), ref_text="Hi.")
    }


def test_cloning_without_a_transcript_says_what_is_missing(tmp_path):
    clip = tmp_path / "me.wav"
    clip.write_bytes(b"RIFF")

    with pytest.raises(ValueError, match="reference WAV and its transcript"):
        vui.create({"vc_vui_voice": vui.CLONE, "vc_tts_ref_audio": str(clip)})


# -- what the session tells the model, and the TTS ------------------------------


def test_the_prompt_asks_for_english_and_lists_vuis_tags_when_asked():
    assert engine_vc._voice_note(_VUI) == vui.prompt_note(_VUI)
    assert "English only" in engine_vc._voice_note(_VUI)

    note = engine_vc._voice_note({**_VUI, "vc_tts_audio_tags": True})

    assert "[laugh]" in note and "[whispers]" not in note
    assert note.endswith(vui.prompt_note(_VUI))


def test_another_voice_gets_no_language_note():
    assert engine_vc._voice_note({"vc_tts_provider": "piper"}) == ""


def test_vuis_own_tags_pass_and_any_other_is_stripped():
    spoken = build_tts_filter(_VUI)("[laugh] Okay [smiles] that is it [sigh] 🙂")

    assert spoken == "[laugh] Okay that is it [sigh]"


def test_vui_hears_the_dialogue_with_the_users_voice():
    context = tts_context(vui.create({})[0])

    assert context is not None and context.include_audio
    assert tts_context(object()) is None  # a TTS that takes no dialogue


# -- engine cache ----------------------------------------------------------------


@pytest.fixture
def engine(qapp, monkeypatch):
    built: list[AsyncMock] = []

    def create(name, settings):
        tts = AsyncMock()
        built.append(tts)
        return tts, 24000

    monkeypatch.setattr(engine_vc, "create_tts_provider", create)
    eng = Engine()
    eng.built = built
    return eng


def test_vui_is_a_cached_local_voice():
    assert is_cached_tts("vui")


async def test_the_same_voice_reuses_the_cached_vui(engine):
    first, _ = await engine._build_tts({**_VUI, "vc_vui_voice": "harry"}, "cuda")
    second, _ = await engine._build_tts({**_VUI, "vc_vui_voice": "harry"}, "cuda")

    assert first is second
    assert len(engine.built) == 1


async def test_another_voice_closes_the_cached_one_before_loading(engine):
    first, _ = await engine._build_tts({**_VUI, "vc_vui_voice": "harry"}, "cuda")
    second, _ = await engine._build_tts({**_VUI, "vc_vui_voice": "rhian"}, "cuda")

    assert first is not second
    first.close.assert_awaited_once()
    second.close.assert_not_awaited()


async def test_a_clip_recorded_again_in_place_rebuilds_it(engine, tmp_path):
    clip = tmp_path / "me.wav"
    clip.write_bytes(b"RIFF")
    settings = {
        **_VUI,
        "vc_vui_voice": vui.CLONE,
        "vc_tts_ref_audio": str(clip),
        "vc_tts_ref_text": "Hi.",
    }
    first, _ = await engine._build_tts(settings, "cuda")

    stat = clip.stat()
    os.utime(clip, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    second, _ = await engine._build_tts(settings, "cuda")

    assert first is not second


# -- install ---------------------------------------------------------------------


def test_a_python_vui_does_not_run_on_is_said_and_never_installed(monkeypatch):
    refused = Feature("vui", "Vui", ("module_nobody_has",), python_below=(3, 0))
    monkeypatch.setitem(features.FEATURES, "vui", refused)

    reason = features.unavailable_reason("vui")
    plan = components.install_plan(components.component_of("vui"))

    assert reason is not None and reason.startswith("Vui needs Python older than 3.0;")
    assert plan.how is components.Installer.NONE
    assert plan.note.startswith("It needs Python older than 3.0;")
    assert "roomkit-ui[vui]" not in features.format_report()


def test_a_python_vui_runs_on_offers_the_install(monkeypatch):
    accepted = Feature("vui", "Vui", ("module_nobody_has",), python_below=(99, 0))
    monkeypatch.setitem(features.FEATURES, "vui", accepted)

    assert features.unavailable_reason("vui").endswith("Components.")
    assert components.install_plan(components.component_of("vui")).how is not (
        components.Installer.NONE
    )


# -- settings page ---------------------------------------------------------------


def test_the_settings_page_offers_vui_and_its_voices(qapp):
    page = VoiceSetup({**_DEFAULTS, **_VUI, "vc_vui_voice": "abraham"})
    try:
        local = page._local
        assert ("Vui (local, English, NVIDIA GPU)", "vui") in VC_TTS_PROVIDERS
        assert not local.vc_vui_voice.isHidden()
        assert local.vc_tts_ref_audio.isHidden()  # a preset needs no clip
        assert page.get_settings()["vc_vui_voice"] == "abraham"

        local.vc_vui_voice.setCurrentIndex(local.vc_vui_voice.findData(vui.CLONE))

        assert not local.vc_tts_ref_audio.isHidden()
        assert not local.vc_tts_ref_text.isHidden()
        assert page.get_settings()["vc_vui_voice"] == vui.CLONE
    finally:
        shiboken6.delete(page)


def test_another_voice_hides_vuis_fields(qapp):
    page = VoiceSetup({**_DEFAULTS, "vc_tts_provider": "pocket", "vc_vui_voice": vui.CLONE})
    try:
        local = page._local
        assert local.vc_vui_voice.isHidden()
        assert local.vc_tts_ref_audio.isHidden()
    finally:
        shiboken6.delete(page)

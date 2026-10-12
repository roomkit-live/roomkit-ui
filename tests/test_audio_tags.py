"""Audio tags: the model directs a voice that performs them, and only such a voice.

ElevenLabs v3/v4 and Gemini TTS act out "[whispers]" or "[laughs]" instead
of reading them.  With the option on, the system prompt hands the model the
tags its voice performs, and the TTS filter lets them through.
"""

import pytest
import shiboken6

from roomkit_ui.audio_tags import audio_tags_note, performed_tags
from roomkit_ui.engine_vc_helpers import build_tts_filter
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.widgets.settings.voice_setup import VoiceSetup

_GEMINI = {"vc_tts_provider": "gemini"}


@pytest.mark.parametrize(
    ("settings", "has"),
    [
        (_GEMINI, "[short pause]"),
        ({"vc_tts_provider": "elevenlabs", "elevenlabs_model": ""}, "[pause]"),  # v4
        ({"vc_tts_provider": "elevenlabs", "elevenlabs_model": "eleven_v4_turbo"}, "[pause]"),
        ({"vc_tts_provider": "elevenlabs", "elevenlabs_model": "eleven_v3"}, "[slow]"),
    ],
)
def test_a_voice_that_performs_tags_lists_its_own(settings, has):
    tags = performed_tags(settings)

    assert {"[laughs]", "[whispers]", has} <= set(tags)


@pytest.mark.parametrize(
    "settings",
    [
        {"vc_tts_provider": "piper"},
        {"vc_tts_provider": "azure"},
        {"vc_tts_provider": "elevenlabs", "elevenlabs_model": "eleven_flash_v2_5"},
    ],
)
def test_a_voice_that_would_read_them_gets_none(settings):
    assert performed_tags(settings) == ()
    assert audio_tags_note({**settings, "vc_tts_audio_tags": True}) == ""


def test_the_prompt_hands_the_tags_over_only_when_asked():
    assert audio_tags_note(_GEMINI) == ""

    note = audio_tags_note({**_GEMINI, "vc_tts_audio_tags": True})

    assert "[whispers]" in note
    assert "[short pause]" in note
    assert "in English" in note


def test_gemini_keeps_the_tags_it_performs():
    spoken = build_tts_filter(_GEMINI)("[whispers] Here is the secret 🤫 [laughs]")

    assert spoken == "[whispers] Here is the secret [laughs]"


def test_the_note_joins_the_users_prompt_and_survives_an_attitude(qapp):
    from roomkit_ui.engine import Engine

    engine = Engine()
    note = audio_tags_note({**_GEMINI, "vc_tts_audio_tags": True})

    prompt = engine._compose_session_prompt({"system_prompt": "Be brief."}, voice_note=note)
    engine._attitude = "Arr."

    assert prompt == f"Be brief.\n\n{note}"
    assert engine._session_prompt() == f"Be brief.\n\n{note}\n\n# Attitude\nArr."


async def test_a_voice_channel_start_puts_the_note_in_its_prompt(qapp, monkeypatch):
    """The prompt is composed before anything is built: the STT, built
    first, sees the note in it."""
    from roomkit_ui.engine import Engine

    engine = Engine()
    prompts = []

    async def no_stt(*_args):
        prompts.append(engine._base_system_prompt)
        raise RuntimeError("no STT in this test")

    monkeypatch.setattr(engine, "_build_stt", no_stt)
    await engine._start_voice_channel(
        {**_DEFAULTS, **_GEMINI, "system_prompt": "Be brief.", "vc_tts_audio_tags": True}
    )

    assert prompts[0].startswith("Be brief.\n\nYour voice performs audio tags.")
    assert "[whispers]" in prompts[0]


# -- settings ----------------------------------------------------------------------------


def test_the_option_is_offered_where_the_voice_performs_tags(qapp):
    page = VoiceSetup({**_DEFAULTS, **_GEMINI, "vc_tts_audio_tags": True})
    try:
        cloud = page._cloud
        assert cloud.vc_tts_audio_tags.isEnabled()
        assert "[whispers]" in cloud._audio_tags_note.text()
        assert page.get_settings()["vc_tts_audio_tags"] is True
    finally:
        shiboken6.delete(page)


def test_a_voice_that_would_read_them_keeps_the_choice_disabled(qapp):
    page = VoiceSetup({**_DEFAULTS, "vc_tts_provider": "piper", "vc_tts_audio_tags": True})
    try:
        cloud = page._cloud
        assert not cloud.vc_tts_audio_tags.isEnabled()
        assert "read them aloud" in cloud._audio_tags_note.text()
        assert page.get_settings()["vc_tts_audio_tags"] is True  # kept for another voice
    finally:
        shiboken6.delete(page)


def test_the_elevenlabs_model_decides(qapp):
    page = VoiceSetup({**_DEFAULTS, "vc_tts_provider": "elevenlabs"})
    try:
        cloud = page._cloud
        assert cloud.vc_tts_audio_tags.isEnabled()  # v4 by default

        cloud.elevenlabs_model.setCurrentIndex(cloud.elevenlabs_model.findData("eleven_flash_v2"))

        assert not cloud.vc_tts_audio_tags.isEnabled()
    finally:
        shiboken6.delete(page)

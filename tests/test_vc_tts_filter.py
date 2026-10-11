"""What the voice never reads aloud, and the chat showing what it said.

Models put emoji, a JSON tool call written as words, a "(Note: ...)" to
themselves or "[smiles]" into replies; a TTS reads them out. The voice
channel now filters them — keeping ElevenLabs audio tags on the models that
perform them — and the assistant bubble shows the filtered text, on both
delivery paths: sentence by sentence (a TTS fed streamed text) and whole (a
TTS that is not: Piper, Qwen3, NeuTTS).
"""

import pytest
from roomkit.voice.tts.mock import MockTTSProvider
from vc_harness import StreamingInputTTS, open_session, until

from roomkit_ui.engine_vc_helpers import build_tts_filter

_PIPER = {"vc_tts_provider": "piper"}

# A reply streamed in tokens, its JSON cut across them.
_REPLY = [
    "Sure 😀 [smiles] here it is. ",
    '{"tool": "wea',
    'ther", "city": "Paris"} ',
    "(Note: check the unit) ",
    "--- It is sunny.",
]
_SPOKEN = "Sure here it is. It is sunny."


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ('Ok 👍 {"name": "x"} done.', "Ok done."),
        ("(NB: internal) Voilà ✅ c'est fait.", "Voilà c'est fait."),
        ("[laughs] That's funny --- really.", "That's funny really."),
        ("A (short) pause, well-known -- fine.", "A (short) pause, well-known -- fine."),
    ],
)
def test_the_voice_skips_what_is_not_meant_to_be_heard(text, spoken):
    assert build_tts_filter(_PIPER)(text) == spoken


@pytest.mark.parametrize("model", ["", "eleven_v3", "eleven_v4", "eleven_v4_turbo"])
def test_elevenlabs_keeps_the_audio_tags_its_expressive_models_perform(model):
    settings = {"vc_tts_provider": "elevenlabs", "elevenlabs_model": model}

    assert build_tts_filter(settings)("[laughs] That's funny 😀") == "[laughs] That's funny"


def test_elevenlabs_drops_them_on_a_model_that_would_read_them():
    settings = {"vc_tts_provider": "elevenlabs", "elevenlabs_model": "eleven_flash_v2_5"}

    assert build_tts_filter(settings)("[laughs] That's funny") == "That's funny"


async def test_a_streamed_reply_is_spoken_and_shown_filtered():
    tts = StreamingInputTTS()
    vc = await open_session(tts=tts, reply=_REPLY, tts_filter=build_tts_filter(_PIPER))
    try:
        await vc.speak()
        await until(lambda: vc.engine.finals("assistant"))

        # A streamed removal leaves its spaces behind, which no voice reads.
        assert " ".join(" ".join(tts.spoken).split()) == _SPOKEN
        assistant = [text for text, role, _, _ in vc.engine.chat if role == "assistant"]
        assert assistant[-1] == _SPOKEN  # the final bubble is what was said
        assert all(text in _SPOKEN for text in assistant)  # and so was every partial
    finally:
        await vc.kit.close()


async def test_a_reply_delivered_whole_never_shows_what_was_not_said():
    """BEFORE_TTS sees a whole reply before the channel filters it: without the
    bubble filtering it too, the emoji and the JSON stayed on screen for as
    long as the reply played."""
    tts = MockTTSProvider()
    vc = await open_session(tts=tts, reply=_REPLY, tts_filter=build_tts_filter(_PIPER))
    try:
        await vc.speak()
        await until(lambda: vc.engine.finals("assistant"))

        assert [call["text"] for call in tts.calls] == [_SPOKEN]
        assistant = [text for text, role, _, _ in vc.engine.chat if role == "assistant"]
        assert assistant == [_SPOKEN, _SPOKEN]  # the partial, then the final
    finally:
        await vc.kit.close()

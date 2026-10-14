"""Kokoro TTS provider factory: Kokoro-82M through sherpa-onnx, local, CPU or CUDA."""

from __future__ import annotations

from typing import Any

SAMPLE_RATE = 24000

# The 54 voices of sherpa-onnx's kokoro-multi-lang-v1_0, in voices.bin order:
# a voice is its index there (sherpa-onnx prints the table when it loads).
_VOICES_BIN = (
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore", "af_nicole",
    "af_nova", "af_river", "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir",
    "am_liam", "am_michael", "am_onyx", "am_puck", "am_santa", "bf_alice", "bf_emma",
    "bf_isabella", "bf_lily", "bm_daniel", "bm_fable", "bm_george", "bm_lewis", "ef_dora",
    "em_alex", "ff_siwis", "hf_alpha", "hf_beta", "hm_omega", "hm_psi", "if_sara", "im_nicola",
    "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo", "pf_dora", "pm_alex",
    "pm_santa", "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi", "zm_yunjian", "zm_yunxi",
    "zm_yunxia", "zm_yunyang", "em_santa",
)  # fmt: skip

# A voice name's first letter → its language, the espeak-ng language sherpa-onnx
# reads that text in ("" = its English and Chinese lexicons), and the English
# lexicon. Only languages a transcription read back (2026-10-14, Whisper small):
# word for word, Portuguese but for one word. Hindi, Japanese and Mandarin came
# back garbled, so their voices are not offered.
_LANGUAGES = {
    "a": ("American English", "", "us"),
    "b": ("British English", "", "gb"),
    "f": ("French", "fr", "us"),
    "e": ("Spanish", "es", "us"),
    "i": ("Italian", "it", "us"),
    "p": ("Brazilian Portuguese", "pt-br", "us"),
}

# The voice a speech-recognition language gets when none is chosen.
_STT_DEFAULTS = {
    "en": "af_heart",
    "fr": "ff_siwis",
    "es": "ef_dora",
    "it": "if_sara",
    "pt": "pf_dora",
}
_DEFAULT_VOICE = "af_heart"


def _label(name: str) -> str:
    language = _LANGUAGES[name[0]][0]
    gender = "female" if name[1] == "f" else "male"
    return f"{language} · {name[3:].capitalize()} ({gender})"


# (label, voice name) for the voices offered, grouped by language.
VOICES: tuple[tuple[str, str], ...] = tuple(
    (_label(name), name) for prefix in _LANGUAGES for name in _VOICES_BIN if name[0] == prefix
)


def create(settings: dict) -> tuple[Any, int]:
    """Create a Kokoro provider. Returns (provider, 24000)."""
    from roomkit.voice.tts.sherpa_onnx import SherpaOnnxTTSConfig, SherpaOnnxTTSProvider

    from roomkit_ui.model_catalog import is_kokoro_downloaded, kokoro_model_path

    if not is_kokoro_downloaded():
        raise ValueError(
            "Kokoro is not downloaded. Download it in Models & components, "
            "then pick its voice in Conversation → Speak."
        )
    voice = _voice(settings)
    _, lang, english = _LANGUAGES[voice[0]]
    d = kokoro_model_path()
    config = SherpaOnnxTTSConfig(
        model_type="kokoro",
        model=str(d / "model.int8.onnx"),
        voices=str(d / "voices.bin"),
        tokens=str(d / "tokens.txt"),
        data_dir=str(d / "espeak-ng-data"),
        lexicon=f"{d / f'lexicon-{english}-en.txt'},{d / 'lexicon-zh.txt'}",
        lang=lang,
        speaker_id=_VOICES_BIN.index(voice),
        sample_rate=SAMPLE_RATE,
        provider=settings.get("inference_device", "cpu"),
    )
    return SherpaOnnxTTSProvider(config), SAMPLE_RATE


def cache_fields(settings: dict) -> tuple:
    """The voice, whose language the model is loaded for: a change rebuilds it."""
    return (_voice(settings),)


def voice_label(speaker_id: str) -> str:
    """The label of the voice at *speaker_id* in voices.bin, for session details."""
    try:
        name = _VOICES_BIN[int(speaker_id)]
    except (ValueError, IndexError):
        return speaker_id
    return _label(name) if name[0] in _LANGUAGES else name


def _voice(settings: dict) -> str:
    """The chosen voice, or by default the speech-recognition language's."""
    chosen = (settings.get("vc_kokoro_voice", "") or "").strip()
    if chosen in _VOICES_BIN and chosen[0] in _LANGUAGES:
        return chosen
    stt_language = (settings.get("stt_language", "") or "").strip()
    return _STT_DEFAULTS.get(stt_language, _DEFAULT_VOICE)

"""Voice Channel STT builders: the cloud providers, and the VAD a turnless one needs.

Each cloud builder takes the settings and a status callback, and refuses a
missing key or endpoint with a ``ValueError`` the start reports.  The local
STT (sherpa-onnx) is cached across sessions and stays in ``engine_vc``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from roomkit_ui.engine_vc_helpers import try_set_float, try_set_int
from roomkit_ui.features import is_available

logger = logging.getLogger(__name__)


def _stt_language(settings: dict) -> str:
    """The app's STT language, English when none is set."""
    return str(settings.get("stt_language", "") or "en")


def build_gradium_stt(settings: dict, emit_status: Callable[[str], None]) -> Any:
    from roomkit.voice.stt.gradium import GradiumSTTConfig, GradiumSTTProvider

    emit_status("Connecting Gradium STT…")
    api_key = settings.get("gradium_api_key", "")
    if not api_key:
        raise ValueError("Gradium API key is required for Gradium STT.")
    region = settings.get("gradium_region", "us")
    # Prefer Gradium-specific language, fall back to global
    stt_language = settings.get("gradium_language", "") or _stt_language(settings)

    stt_kwargs: dict[str, Any] = {}
    model_name = settings.get("gradium_stt_model", "")
    if model_name:
        stt_kwargs["model_name"] = model_name
    try_set_int(stt_kwargs, "delay_in_frames", settings.get("gradium_stt_delay", ""))
    try_set_float(stt_kwargs, "vad_threshold", settings.get("gradium_vad_threshold", ""))
    try_set_int(stt_kwargs, "vad_steps", settings.get("gradium_vad_steps", ""))

    json_config: dict[str, Any] = {}
    try_set_float(json_config, "temperature", settings.get("gradium_stt_temperature", ""))
    if json_config:
        stt_kwargs["json_config"] = json_config

    stt_config = GradiumSTTConfig(
        api_key=api_key, region=region, language=stt_language, **stt_kwargs
    )
    logger.info("STT: gradium, region=%s, language=%s", region, stt_language)
    return GradiumSTTProvider(stt_config)


def build_deepgram_stt(settings: dict, emit_status: Callable[[str], None]) -> Any:
    from roomkit.voice.stt.deepgram import DeepgramConfig, DeepgramSTTProvider

    emit_status("Connecting Deepgram STT…")
    api_key = settings.get("deepgram_api_key", "")
    if not api_key:
        raise ValueError("Deepgram API key is required for Deepgram STT.")
    dg_model = settings.get("deepgram_model", "nova-3")
    stt_language = _stt_language(settings)
    dg_config = DeepgramConfig(api_key=api_key, model=dg_model, language=stt_language)
    logger.info("STT: deepgram, model=%s, language=%s", dg_model, stt_language)
    return DeepgramSTTProvider(dg_config)


def build_azure_mai_stt(settings: dict, emit_status: Callable[[str], None]) -> Any:
    """Microsoft MAI-Transcribe on a Foundry resource (public preview).

    The language is the app's STT language when one is set, else the service
    detects it utterance by utterance; a code MAI-Transcribe does not take is
    refused here with the list of those it does.
    """
    from roomkit.voice.stt.azure_mai import (
        DEFAULT_DEPLOYMENT,
        AzureMAISTTConfig,
        AzureMAISTTProvider,
    )

    emit_status("Connecting Azure MAI-Transcribe…")
    api_key = settings.get("azure_speech_api_key", "")
    endpoint = (settings.get("azure_mai_endpoint", "") or "").strip()
    if not api_key or not endpoint:
        raise ValueError(
            "Azure MAI-Transcribe needs the Foundry resource's key and endpoint "
            "(https://<resource>.services.ai.azure.com). Open Settings to enter them."
        )
    config = AzureMAISTTConfig(
        endpoint=endpoint,
        api_key=api_key,
        deployment=(settings.get("azure_mai_deployment", "") or "").strip() or DEFAULT_DEPLOYMENT,
        language=(settings.get("stt_language", "") or "").strip() or None,
    )
    logger.info("STT: azure_mai, deployment=%s, language=%s", config.deployment, config.language)
    return AzureMAISTTProvider(config)


# The app's STT language codes → the names Muse takes as a language bias
# (roomkit's meta.SUPPORTED_LANGUAGES: it ignores a code like "fr" silently).
_META_LANGUAGES = {
    "ar": "Arabic",
    "bn": "Bengali",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "kn": "Kannada",
    "ko": "Korean",
    "mr": "Marathi",
    "ms": "Malay",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tl": "Tagalog",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "zh": "Mandarin Chinese",
}


def labels_speakers(settings: dict) -> bool:
    """Whether the session's STT tells the voices apart: Muse, with speaker
    identification on (Settings → Speakers)."""
    return bool(settings.get("diarization_enabled")) and settings.get("vc_stt_provider") == "meta"


def build_meta_stt(settings: dict, emit_status: Callable[[str], None]) -> Any:
    """Meta's Muse Voice Transcribe, streaming over Meta's websocket.

    The model ends each turn itself (``ENDPOINTING``): a cloud STT gets no
    pipeline VAD, so the channel streams all the audio to it.  With speaker
    identification on it also labels each turn's voice (``DIARIZATION``),
    and a change of voice ends a turn even without a pause.  The app's STT
    language becomes a bias, not a pin, and with none set the model takes
    what it hears; a language Muse does not transcribe is refused here.
    """
    from roomkit.voice.stt.meta import MetaSTTConfig, MetaSTTProvider

    from roomkit_ui.constants import STT_LANGUAGES

    emit_status("Connecting Meta Muse STT…")
    api_key = str(settings.get("meta_api_key", "") or "").strip()
    if not api_key:
        raise ValueError("Meta API key is required for Meta Muse STT.")
    code = str(settings.get("stt_language", "") or "").strip()
    bias = _META_LANGUAGES.get(code)
    if code and bias is None:
        name = dict((value, label) for label, value in STT_LANGUAGES).get(code, code)
        raise ValueError(
            f"Meta Muse does not transcribe {name}. Pick another language "
            "(Settings → Dictation) or another STT."
        )
    keywords = [
        word.strip() for word in str(settings.get("meta_stt_keywords", "") or "").split(",")
    ]
    config = MetaSTTConfig(
        api_key=api_key,
        mode="DIARIZATION" if labels_speakers(settings) else "ENDPOINTING",
        language_bias=[bias] if bias else [],
        keywords=[word for word in keywords if word],
    )
    logger.info(
        "STT: meta, mode=%s, language bias=%s, %d keywords",
        config.mode,
        bias or "none",
        len(config.keywords),
    )
    return MetaSTTProvider(config)


# Google's one live recogniser (roomkit's GeminiTranscribeConfig default); the
# batch gemini-3.5-transcribe takes a whole recording, not a stream.
GEMINI_STT_MODEL = "gemini-3.5-transcribe-live"


def build_gemini_stt(settings: dict, emit_status: Callable[[str], None]) -> Any:
    """Google's live recogniser (``gemini-3.5-transcribe-live``) over the Gemini API.

    It ends each turn itself, like Deepgram: the channel gets no pipeline
    VAD and streams all the audio to it, and roomkit reconnects when Google
    closes a session at its ten-minute cap.  The app's STT language is its
    one hint; with none set it detects the language among the 85+ it takes.
    The key is the one Gemini Live and the LLM use.
    """
    from roomkit.voice.stt.gemini_transcribe import (
        GeminiTranscribeConfig,
        GeminiTranscribeProvider,
    )

    emit_status("Connecting Gemini STT…")
    api_key = str(settings.get("api_key", "") or "").strip()
    if not api_key:
        raise ValueError("Google API key is required for Gemini STT. Open Settings to enter it.")
    language = str(settings.get("stt_language", "") or "").strip()
    vocabulary = [
        term.strip() for term in str(settings.get("gemini_stt_vocabulary", "") or "").split(",")
    ]
    config = GeminiTranscribeConfig(
        api_key=api_key,
        model=str(settings.get("gemini_stt_model", "") or "").strip() or GEMINI_STT_MODEL,
        language_codes=[language] if language else [],
        custom_vocabulary=[term for term in vocabulary if term],
    )
    logger.info(
        "STT: gemini, model=%s, language=%s, %d vocabulary terms",
        config.model,
        language or "detected",
        len(config.custom_vocabulary),
    )
    return GeminiTranscribeProvider(config)


# vc_stt_provider → its builder.  A provider absent here is the local one.
CLOUD_STT_BUILDERS: dict[str, Callable[[dict, Callable[[str], None]], Any]] = {
    "gradium": build_gradium_stt,
    "deepgram": build_deepgram_stt,
    "azure_mai": build_azure_mai_stt,
    "meta": build_meta_stt,
    "gemini": build_gemini_stt,
}


# STT providers that detect no turns: they transcribe until the client
# commits, so the voice channel needs a pipeline VAD to end each utterance.
_TURNLESS_STT = frozenset({"azure_mai"})

# roomkit's MAI example waits 800 ms of silence, not the VAD's usual 500: at
# 500 a pause mid-sentence ended the turn and a cut word came back in halves.
_TURNLESS_SILENCE_MS = 800


def stt_needs_turn_vad(stt_provider_name: str) -> bool:
    """Whether this STT finds no turns itself and must have a pipeline VAD."""
    return stt_provider_name in _TURNLESS_STT


def build_turn_vad(settings: dict, inference_device: str) -> Any:
    """The VAD a turnless STT needs: the chosen local model, else an energy VAD.

    Never None: without a VAD such an STT never commits, and no transcript
    ever comes.  The energy VAD needs no model, so it is always there.
    """
    from roomkit_ui.model_manager import build_vad_config, is_vad_model_downloaded

    tuned = dict(settings)
    if not str(tuned.get("vad_silence_ms", "") or "").strip():
        tuned["vad_silence_ms"] = str(_TURNLESS_SILENCE_MS)
    vad_model_id = settings.get("vc_vad_model", "")
    # The VAD models run on sherpa-onnx; without it, the energy VAD.
    if vad_model_id and is_vad_model_downloaded(vad_model_id) and is_available("local-voice"):
        from roomkit.voice.pipeline.vad.sherpa_onnx import SherpaOnnxVADProvider

        logger.info("VAD: %s (turns for a turnless STT)", vad_model_id)
        config = build_vad_config(vad_model_id, provider=inference_device, settings=tuned)
        return SherpaOnnxVADProvider(config)

    from roomkit.voice.pipeline.vad.energy import EnergyVADProvider

    try:
        silence_ms = float(tuned["vad_silence_ms"])
    except (TypeError, ValueError):
        silence_ms = float(_TURNLESS_SILENCE_MS)
    logger.info("VAD: energy, silence=%.0fms (no VAD model downloaded)", silence_ms)
    return EnergyVADProvider(silence_threshold_ms=silence_ms)

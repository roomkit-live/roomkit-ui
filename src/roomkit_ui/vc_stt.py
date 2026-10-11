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


# vc_stt_provider → its builder.  A provider absent here is the local one.
CLOUD_STT_BUILDERS: dict[str, Callable[[dict, Callable[[str], None]], Any]] = {
    "gradium": build_gradium_stt,
    "deepgram": build_deepgram_stt,
    "azure_mai": build_azure_mai_stt,
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
    if vad_model_id and is_vad_model_downloaded(vad_model_id):
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

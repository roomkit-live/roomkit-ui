"""Stateless builders for the Voice-Channel session (no engine state).

Extracted from :mod:`roomkit_ui.engine_vc` so the mixin file keeps only
the session orchestration; everything here is a pure function of the
settings dict (plus emit callbacks for UI status/errors).
"""

from __future__ import annotations

import logging
from typing import Any

from roomkit_ui.mcp_config import has_enabled_mcp_servers

logger = logging.getLogger(__name__)


def build_gradium_stt(settings: dict, stt_language: str, emit_status) -> Any:
    from roomkit.voice.stt.gradium import GradiumSTTConfig, GradiumSTTProvider

    emit_status("Connecting Gradium STT…")
    api_key = settings.get("gradium_api_key", "")
    if not api_key:
        raise ValueError("Gradium API key is required for Gradium STT.")
    region = settings.get("gradium_region", "us")
    # Prefer Gradium-specific language, fall back to global
    gradium_lang = settings.get("gradium_language", "")
    if gradium_lang:
        stt_language = gradium_lang

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


def build_deepgram_stt(settings: dict, stt_language: str, emit_status) -> Any:
    from roomkit.voice.stt.deepgram import DeepgramConfig, DeepgramSTTProvider

    emit_status("Connecting Deepgram STT…")
    api_key = settings.get("deepgram_api_key", "")
    if not api_key:
        raise ValueError("Deepgram API key is required for Deepgram STT.")
    dg_model = settings.get("deepgram_model", "nova-3")
    dg_config = DeepgramConfig(api_key=api_key, model=dg_model, language=stt_language)
    logger.info("STT: deepgram, model=%s, language=%s", dg_model, stt_language)
    return DeepgramSTTProvider(dg_config)


# How Ollama words a model refusing the tools it was given.
LOCAL_TOOL_REFUSAL = "does not support tools"
_NO_TOOLS_HINT = (
    'This model does not support tool use. Disable "Model supports tool use" in '
    "Settings → AI Provider."
)


def register_local_tool_hint(kit: Any, emit_error) -> None:
    """Point at the setting when a local model refuses the tools it was given.

    The refusal (Ollama: "<model> does not support tools") fails the turn
    inside the AIChannel's streamed generation, and roomkit hands every such
    turn failure to the ON_ERROR hooks with the provider's message in
    ``metadata["error"]``.  Said once per session: every turn fails alike.
    """
    from roomkit.models.enums import HookExecution, HookTrigger

    shown = False

    @kit.hook(HookTrigger.ON_ERROR, HookExecution.ASYNC)
    async def _on_tool_refusal(event: Any, context: Any) -> None:
        nonlocal shown
        error = str((getattr(event, "metadata", None) or {}).get("error", ""))
        if shown or LOCAL_TOOL_REFUSAL not in error:
            return
        shown = True
        try:
            emit_error(_NO_TOOLS_HINT)
        except Exception:
            logger.debug("emit_error failed (Qt object deleted?)", exc_info=True)


def build_interruption(settings: dict) -> Any:
    from roomkit.voice.interruption import InterruptionConfig, InterruptionStrategy

    enabled = settings.get("vc_interruption", False)
    strategy = InterruptionStrategy.IMMEDIATE if enabled else InterruptionStrategy.DISABLED
    logger.info("Interruption: %s", strategy.value)
    return InterruptionConfig(strategy=strategy)


def build_turn_detector(settings: dict, inference_device: str) -> Any:
    td_name = settings.get("vc_turn_detector", "")
    if td_name != "smart-turn":
        return None

    from roomkit_ui.model_manager import is_smart_turn_downloaded, smart_turn_model_path

    if not is_smart_turn_downloaded():
        logger.warning("Smart Turn model not downloaded — skipping")
        return None

    from roomkit.voice.pipeline.turn.smart_turn import SmartTurnConfig, SmartTurnDetector

    threshold_str = settings.get("vc_turn_threshold", "")
    threshold = 0.5
    if threshold_str:
        try:
            threshold = float(threshold_str)
        except (ValueError, TypeError):
            pass
    logger.info("Turn detector: smart-turn, threshold=%.2f", threshold)
    return SmartTurnDetector(
        SmartTurnConfig(
            model_path=str(smart_turn_model_path()),
            threshold=threshold,
            provider=inference_device,
        )
    )


def log_vc_audio_pipeline(
    aec: Any, denoiser: Any, input_sample_rate: int, output_sample_rate: int
) -> None:
    aec_label = type(aec).__name__ if aec else "none"
    denoise_label = type(denoiser).__name__ if denoiser else "none"
    logger.info(
        "VC audio pipeline: aec=%s, denoiser=%s, in_rate=%dHz, out_rate=%dHz",
        aec_label,
        denoise_label,
        input_sample_rate,
        output_sample_rate,
    )


def mcp_servers_configured(settings: dict) -> bool:
    return has_enabled_mcp_servers(settings.get("mcp_servers", "[]"))


def try_set_int(target: dict[str, Any], key: str, raw: str) -> None:
    if not raw:
        return
    try:
        target[key] = int(raw)
    except (ValueError, TypeError):
        pass


def try_set_float(target: dict[str, Any], key: str, raw: str) -> None:
    if not raw:
        return
    try:
        target[key] = float(raw)
    except (ValueError, TypeError):
        pass


def announce_llm_model(provider: Any, emit_notice) -> None:
    """Say in the chat what the user should know about the session's model.

    Once, that a retired default was moved to its successor (see
    ``settings._RETIRED_DEFAULTS``).  Every session, that a model the user
    kept is deprecated in roomkit's catalog: it stops answering on the
    vendor's retirement date, and a deliberate pick is not overridden.
    """
    from roomkit_ui.settings import take_model_notices

    for notice in take_model_notices():
        emit_notice(notice)
    try:
        entry = provider.catalog_entry()
    except Exception:
        return
    if entry is not None and getattr(entry, "deprecated", False):
        name = getattr(entry, "display_name", None) or entry.id
        emit_notice(
            f"{name} is deprecated by its vendor and will stop answering. "
            "Pick another model in Settings → AI Provider → LLM."
        )


async def start_local_llm(provider: Any, emit_status) -> None:
    """Start a model roomkit runs itself before the session opens the mic.

    llama.cpp downloads llama-server and the model the first time, and loads
    the model at each server start: left to the first turn, the user's first
    sentence would wait in silence for it — minutes on a first run.  The
    server outlives the session (providers/llamacpp.py), so later sessions
    find it running and return at once.
    """
    if getattr(provider, "name", "") != "llamacpp":
        return
    emit_status("Starting llama.cpp — the first run downloads the model…")
    await provider.start()


def build_azure_mai_stt(settings: dict, emit_status) -> Any:
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

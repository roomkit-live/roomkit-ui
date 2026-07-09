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


def wrap_local_provider_tool_errors(ai_provider: Any, emit_error) -> None:
    """Wrap a local AI provider's ``generate`` so tool-not-supported errors surface."""
    _orig_generate = ai_provider.generate
    _tool_error_emitted = False

    async def _generate_with_tool_hint(context: Any) -> Any:
        nonlocal _tool_error_emitted
        try:
            return await _orig_generate(context)
        except Exception as exc:
            if not _tool_error_emitted and "does not support tools" in str(exc):
                _tool_error_emitted = True
                try:
                    emit_error(
                        "This model does not support tool use. "
                        'Disable "Model supports tool use" in '
                        "Settings → AI Provider."
                    )
                except Exception:
                    logger.debug("emit_error failed (Qt object deleted?)", exc_info=True)
            raise

    ai_provider.generate = _generate_with_tool_hint  # type: ignore[method-assign]


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

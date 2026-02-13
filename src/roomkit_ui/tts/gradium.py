"""Gradium cloud TTS provider factory."""

from __future__ import annotations

from typing import Any


def create(settings: dict) -> tuple[Any, int]:
    """Create a Gradium TTS provider. Returns (provider, sample_rate)."""
    from roomkit.voice.tts.gradium import GradiumTTSConfig, GradiumTTSProvider

    api_key = settings.get("gradium_api_key", "")
    if not api_key:
        raise ValueError("Gradium API key is required for Gradium TTS.")
    voice_id = settings.get("vc_gradium_voice", "") or "default"
    region = settings.get("gradium_region", "us")
    output_format = "pcm_24000"

    kwargs: dict[str, Any] = {}
    model_name = settings.get("gradium_tts_model", "")
    if model_name:
        kwargs["model_name"] = model_name
    speed = settings.get("gradium_speed", "")
    if speed:
        try:
            kwargs["padding_bonus"] = float(speed)
        except (ValueError, TypeError):
            pass
    temperature = settings.get("gradium_temperature", "")
    if temperature:
        try:
            kwargs["temperature"] = float(temperature)
        except (ValueError, TypeError):
            pass
    cfg_coef = settings.get("gradium_cfg_coef", "")
    if cfg_coef:
        try:
            kwargs["cfg_coef"] = float(cfg_coef)
        except (ValueError, TypeError):
            pass
    rewrite_rules = settings.get("gradium_rewrite_rules", "")
    if rewrite_rules:
        kwargs["rewrite_rules"] = rewrite_rules

    config = GradiumTTSConfig(
        api_key=api_key,
        voice_id=voice_id,
        region=region,
        output_format=output_format,
        **kwargs,
    )
    return GradiumTTSProvider(config), 24000

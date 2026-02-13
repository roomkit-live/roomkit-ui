"""Piper (sherpa-onnx) TTS provider factory."""

from __future__ import annotations

from typing import Any


def create(settings: dict) -> tuple[Any, int]:
    """Create a Piper/sherpa-onnx TTS provider from settings. Returns (provider, sample_rate)."""
    from roomkit.voice.tts.sherpa_onnx import SherpaOnnxTTSProvider

    from roomkit_ui.model_manager import build_tts_config

    tts_model_id = settings.get("vc_tts_model", "")
    if not tts_model_id:
        raise ValueError(
            "No TTS model selected. Download one in AI Models and select it in Settings."
        )
    inference_device = settings.get("inference_device", "cpu")
    config = build_tts_config(tts_model_id, provider=inference_device)
    return SherpaOnnxTTSProvider(config), config.sample_rate

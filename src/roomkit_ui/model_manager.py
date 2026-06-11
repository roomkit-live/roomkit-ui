"""Download and manage local STT/TTS models from edge-ai-models."""

from __future__ import annotations

import asyncio
import ctypes
import sys

# Names marked "noqa: F401" are re-exports: every symbol previously defined
# here is still importable from this module by external callers.
from roomkit_ui.model_catalog import (
    _MODELS_BY_ID,
    _SPEAKER_MODELS_BY_ID,
    _TTS_MODELS_BY_ID,
    _VAD_MODELS_BY_ID,
    GTCRN_MODEL_ID,  # noqa: F401
    GTCRN_SIZE,  # noqa: F401
    GTCRN_URL,  # noqa: F401
    SMART_TURN_MODEL_ID,  # noqa: F401
    SMART_TURN_SIZE,  # noqa: F401
    SMART_TURN_URL,  # noqa: F401
    SPEAKER_MODELS,  # noqa: F401
    STT_MODELS,  # noqa: F401
    TTS_MODELS,  # noqa: F401
    VAD_MODELS,  # noqa: F401
    SpeakerModel,  # noqa: F401
    STTModel,  # noqa: F401
    TTSModel,  # noqa: F401
    VADModel,  # noqa: F401
    delete_espeak_ng_data,  # noqa: F401
    delete_gtcrn,  # noqa: F401
    delete_model,  # noqa: F401
    delete_smart_turn,  # noqa: F401
    delete_speaker_model,  # noqa: F401
    delete_tts_model,  # noqa: F401
    delete_vad_model,  # noqa: F401
    espeak_ng_data_path,
    get_models_dir,  # noqa: F401
    gtcrn_model_path,  # noqa: F401
    is_espeak_ng_downloaded,  # noqa: F401
    is_gtcrn_downloaded,  # noqa: F401
    is_model_downloaded,  # noqa: F401
    is_smart_turn_downloaded,  # noqa: F401
    is_speaker_model_downloaded,  # noqa: F401
    is_tts_model_downloaded,  # noqa: F401
    is_vad_model_downloaded,  # noqa: F401
    model_path,
    smart_turn_model_path,  # noqa: F401
    speaker_model_path,
    tts_model_path,
    vad_model_path,
)
from roomkit_ui.model_download import (
    ProgressCallback,
    _download_espeak_ng_sync,
    _download_file,  # noqa: F401
    _download_gtcrn_sync,
    _download_model_sync,
    _download_smart_turn_sync,
    _download_speaker_model_sync,
    _download_tts_model_sync,
    _download_vad_model_sync,
    _generate_tokens_txt,  # noqa: F401
    _resolve_lfs_pointer,  # noqa: F401
)


def is_streaming_model(model_id: str) -> bool:
    """Return True if *model_id* is a streaming (transducer) model."""
    m = _MODELS_BY_ID.get(model_id)
    return m is not None and m.type == "streaming"


def _sherpa_mode(model_id: str) -> str:
    """Return the sherpa-onnx mode string for *model_id*."""
    return "whisper" if model_id == "whisper-small" else "transducer"


def detect_providers() -> list[tuple[str, str]]:
    """Return available ONNX execution providers as ``(label, value)`` pairs."""
    providers = [("CPU", "cpu")]
    if sys.platform == "darwin":
        providers.append(("CoreML (Apple GPU)", "coreml"))
    else:
        try:
            ctypes.CDLL("libcuda.so.1")
            providers.append(("CUDA (NVIDIA GPU)", "cuda"))
        except OSError:
            pass
    return providers


def build_stt_config(
    model_id: str,
    language: str = "en",
    *,
    translate: bool = False,
    provider: str = "cpu",
):
    """Build a ``SherpaOnnxSTTConfig`` for the given downloaded model."""
    from roomkit.voice.stt.sherpa_onnx import SherpaOnnxSTTConfig

    m = _MODELS_BY_ID.get(model_id)
    if m is None:
        raise ValueError(f"Unknown model: {model_id}")

    d = model_path(model_id)
    mode = _sherpa_mode(model_id)

    if mode == "whisper":
        return SherpaOnnxSTTConfig(
            mode="whisper",
            encoder=str(d / m.files[0]),
            decoder=str(d / m.files[1]),
            tokens=str(d / m.files[2]),
            language=language or "en",
            task="translate" if translate else "transcribe",
            provider=provider,
        )
    # transducer (parakeet-offline, kroko, zipformer)
    # Offline-only transducers need model_type set so the provider knows
    # they don't support streaming (uses OfflineRecognizer instead).
    model_type = "nemo_transducer" if m.type == "offline" else ""
    return SherpaOnnxSTTConfig(
        mode="transducer",
        encoder=str(d / m.files[0]),
        decoder=str(d / m.files[1]),
        joiner=str(d / m.files[2]),
        tokens=str(d / m.files[3]),
        language=language or "en",
        model_type=model_type,
        provider=provider,
    )


async def download_model(
    model_id: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Download model files in a background thread."""
    await asyncio.to_thread(_download_model_sync, model_id, progress)


async def download_gtcrn(progress: ProgressCallback | None = None) -> None:
    """Download the GTCRN model in a background thread."""
    await asyncio.to_thread(_download_gtcrn_sync, progress)


async def download_vad_model(
    model_id: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Download VAD model in a background thread."""
    await asyncio.to_thread(_download_vad_model_sync, model_id, progress)


def build_vad_config(
    model_id: str,
    *,
    provider: str = "cpu",
    settings: dict | None = None,
):
    """Build a ``SherpaOnnxVADConfig`` for the given downloaded VAD model.

    If *settings* is provided, VAD advanced fields (``vad_threshold``, etc.)
    are read from it; empty strings fall back to SherpaOnnxVADConfig defaults.
    """
    from roomkit.voice.pipeline.vad.sherpa_onnx import SherpaOnnxVADConfig

    m = _VAD_MODELS_BY_ID.get(model_id)
    if m is None:
        raise ValueError(f"Unknown VAD model: {model_id}")

    d = vad_model_path(model_id)
    kwargs: dict = {
        "model": str(d / m.onnx_file),
        "model_type": m.type,
        "provider": provider,
    }

    if settings:
        _float_keys = {
            "vad_threshold": "threshold",
            "vad_silence_ms": "silence_threshold_ms",
            "vad_min_speech_ms": "min_speech_duration_ms",
            "vad_speech_pad_ms": "speech_pad_ms",
            "vad_energy_silence_rms": "energy_silence_rms",
        }
        for settings_key, config_key in _float_keys.items():
            raw = str(settings.get(settings_key, "") or "").strip()
            if raw:
                try:
                    kwargs[config_key] = float(raw)
                except ValueError:
                    pass

    return SherpaOnnxVADConfig(**kwargs)


async def download_smart_turn(progress: ProgressCallback | None = None) -> None:
    """Download the smart-turn model in a background thread."""
    await asyncio.to_thread(_download_smart_turn_sync, progress)


async def download_tts_model(
    model_id: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Download TTS model files in a background thread."""
    await asyncio.to_thread(_download_tts_model_sync, model_id, progress)


async def download_espeak_ng_data(
    progress: ProgressCallback | None = None,
) -> None:
    """Download espeak-ng-data in a background thread."""
    await asyncio.to_thread(_download_espeak_ng_sync, progress)


async def download_speaker_model(
    model_id: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Download speaker embedding model in a background thread."""
    await asyncio.to_thread(_download_speaker_model_sync, model_id, progress)


def build_diarization_config(model_id: str, *, provider: str = "cpu", threshold: float = 0.4):
    """Build a ``SherpaOnnxDiarizationConfig`` for the given downloaded model."""
    from roomkit.voice.pipeline.diarization.sherpa_onnx import SherpaOnnxDiarizationConfig

    m = _SPEAKER_MODELS_BY_ID.get(model_id)
    if m is None:
        raise ValueError(f"Unknown speaker model: {model_id}")

    d = speaker_model_path(model_id)
    return SherpaOnnxDiarizationConfig(
        model=str(d / m.onnx_file),
        provider=provider,
        search_threshold=threshold,
    )


# ---------------------------------------------------------------------------
# TTS config builder
# ---------------------------------------------------------------------------


def build_tts_config(
    model_id: str,
    *,
    provider: str = "cpu",
):
    """Build a ``SherpaOnnxTTSConfig`` for the given downloaded TTS model."""
    from roomkit.voice.tts.sherpa_onnx import SherpaOnnxTTSConfig

    m = _TTS_MODELS_BY_ID.get(model_id)
    if m is None:
        raise ValueError(f"Unknown TTS model: {model_id}")

    d = tts_model_path(model_id)
    return SherpaOnnxTTSConfig(
        model=str(d / m.onnx_file),
        tokens=str(d / "tokens.txt"),
        data_dir=str(espeak_ng_data_path()),
        sample_rate=m.sample_rate,
        provider=provider,
    )

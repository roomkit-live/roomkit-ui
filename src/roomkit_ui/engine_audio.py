"""Pure-function builders used by the voice engine.

None of these touch the ``Engine`` instance — they build pipeline
providers from a settings dict (or reset state on one).  Keeping them
here lets ``engine.py`` stay focused on session lifecycle.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Inbound DSP thread pool (roomkit 0.39+): DO NOT enable on this roomkit.
# On the pool's threads there is no running event loop, and the pipeline's
# _maybe_schedule() DROPS any async callback result ("Async callback
# returned outside event loop") — mic audio never reaches the realtime
# provider and the audio-level hooks (VU meter) go silent.  Re-enable only
# once roomkit's offload schedules coroutines back onto its home loop.
DSP_THREADS: int | None = None


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


def build_telemetry(settings: dict | None):
    """Build a telemetry provider from settings, or ``None`` to use the noop default."""
    if not settings:
        return None
    provider = settings.get("telemetry_provider", "none")
    if provider == "console":
        from roomkit.telemetry import ConsoleTelemetryProvider

        return ConsoleTelemetryProvider()
    if provider == "otlp":
        return _build_otlp_telemetry(settings)
    return None


def _build_otlp_telemetry(settings: dict):
    """Build an OpenTelemetryProvider with an OTLP exporter."""
    try:
        from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
            BatchSpanProcessor,
        )

        service_name = settings.get("otlp_service_name", "") or "roomkit-ui"
        resource = Resource.create({"service.name": service_name})
        tracer_provider = TracerProvider(resource=resource)

        endpoint = settings.get("otlp_endpoint", "").strip()
        protocol = settings.get("otlp_protocol", "grpc")

        if protocol == "http":
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=endpoint or "http://localhost:4318/v1/traces")
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=endpoint or "http://localhost:4317")

        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

        from roomkit.telemetry.opentelemetry import OpenTelemetryProvider

        return OpenTelemetryProvider(tracer_provider=tracer_provider, service_name=service_name)
    except ImportError:
        logger.warning(
            "OpenTelemetry packages not installed — falling back to console telemetry. "
            "Install with: pip install opentelemetry-api opentelemetry-sdk "
            "opentelemetry-exporter-otlp"
        )
        from roomkit.telemetry import ConsoleTelemetryProvider

        return ConsoleTelemetryProvider()


# ---------------------------------------------------------------------------
# Audio debug / recording
# ---------------------------------------------------------------------------


def build_debug_taps(settings: dict):
    """Build a PipelineDebugTaps from settings, or ``None`` if disabled."""
    if not settings.get("debug_taps_enabled"):
        return None
    from pathlib import Path

    from roomkit.voice.pipeline.debug_taps import PipelineDebugTaps

    output_dir = settings.get("debug_output_dir", "").strip()
    if not output_dir:
        output_dir = str(Path.home() / ".local/share/roomkit-ui/debug_audio")
    stages_str = settings.get("debug_taps_stages", "all")
    stages = [s.strip() for s in stages_str.split(",") if s.strip()]
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    return PipelineDebugTaps(output_dir=output_dir, stages=stages)


def build_recorder(settings: dict):
    """Build a (WavFileRecorder, RecordingConfig) pair, or (None, None) if disabled."""
    if not settings.get("recording_enabled"):
        return None, None
    from pathlib import Path

    from roomkit.voice.pipeline.recorder.base import (
        RecordingChannelMode,
        RecordingConfig,
        RecordingMode,
    )
    from roomkit.voice.pipeline.recorder.wav import WavFileRecorder

    output_dir = settings.get("recording_output_dir", "").strip()
    if not output_dir:
        output_dir = str(Path.home() / ".local/share/roomkit-ui/recordings")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    config = RecordingConfig(
        mode=RecordingMode(settings.get("recording_mode", "both")),
        channels=RecordingChannelMode(settings.get("recording_channels", "stereo")),
        storage=output_dir,
    )
    return WavFileRecorder(), config


# ---------------------------------------------------------------------------
# AEC + denoiser
# ---------------------------------------------------------------------------


def build_audio_processing(
    aec_mode: str,
    denoise_mode: str,
    sample_rate: int,
    frame_size: int,
) -> tuple[Any, Any]:
    """Build AEC and denoiser providers. Returns (aec, denoiser)."""
    aec: Any = None
    if aec_mode in ("webrtc", "1"):
        try:
            from roomkit.voice.pipeline.aec.webrtc import WebRTCAECProvider

            aec = WebRTCAECProvider(sample_rate=sample_rate)
        except ImportError:
            logger.warning("WebRTC AEC not available — install aec-audio-processing")
    elif aec_mode == "speex":
        try:
            from roomkit.voice.pipeline.aec.speex import SpeexAECProvider

            aec = SpeexAECProvider(
                frame_size=frame_size,
                filter_length=frame_size * 10,
                sample_rate=sample_rate,
            )
        except ImportError:
            logger.warning("Speex AEC not available — install libspeexdsp")

    denoiser = build_denoiser(denoise_mode, sample_rate)
    return aec, denoiser


def build_denoiser(denoise_mode: str, sample_rate: int) -> Any:
    """Build a denoiser provider for the given mode and sample rate."""
    if denoise_mode == "webrtc":
        try:
            from roomkit.voice.pipeline.denoiser.webrtc import WebRTCNoiseSuppressorProvider

            return WebRTCNoiseSuppressorProvider(sample_rate=sample_rate)
        except ImportError:
            logger.warning("WebRTC noise suppressor not available")
    elif denoise_mode == "rnnoise":
        try:
            from roomkit.voice.pipeline.denoiser.rnnoise import RNNoiseDenoiserProvider

            return RNNoiseDenoiserProvider(sample_rate=sample_rate)
        except ImportError:
            logger.warning("RNNoise denoiser not available")
    elif denoise_mode == "gtcrn":
        from roomkit_ui.model_manager import gtcrn_model_path, is_gtcrn_downloaded

        if is_gtcrn_downloaded():
            from roomkit.voice.pipeline.denoiser.sherpa_onnx import (
                SherpaOnnxDenoiserConfig,
                SherpaOnnxDenoiserProvider,
            )

            return SherpaOnnxDenoiserProvider(
                SherpaOnnxDenoiserConfig(model=str(gtcrn_model_path()))
            )
        logger.warning("GTCRN model not downloaded — denoiser disabled")
    return None


# ---------------------------------------------------------------------------
# Diarization
# ---------------------------------------------------------------------------


def reset_diarization(diarization: Any) -> None:
    """Reset a cached diarization provider and forget all enrolled speakers.

    ``reset()`` clears transient clustering state; ``clear_speakers()`` drops
    the enrollment set so a provider reused across sessions doesn't carry
    speakers between conversations.  Both are public roomkit APIs (0.24.0+).
    """
    diarization.reset()
    diarization.clear_speakers()


def setup_diarization(
    engine: Any,
    settings: dict,
    *,
    vad_available: bool,
    inference_device: str,
) -> Any:
    """Build, cache, and enroll a diarization provider.

    Shared between the realtime and voice-channel startup paths — both
    need the same cache lookup, ``reset_diarization`` on cache hit,
    speaker enrollment, and primary-speaker-mode application.

    Writes these engine attributes as side-effects:

    * ``engine._diarization`` — the provider (or ``None`` when skipped).
    * ``engine._primary_speaker_mode`` — mirror of the user setting.
    * ``engine._primary_speaker_name`` — resolved primary speaker, or ``""``.

    Returns ``None`` when diarization is disabled, unconfigured, missing
    VAD, or missing the speaker model.  Otherwise returns the provider.
    """
    if not settings.get("diarization_enabled"):
        return None
    model_id = settings.get("diarization_model", "")
    if not model_id:
        return None
    if not vad_available:
        logger.warning("Diarization requires VAD — skipping")
        return None

    from roomkit_ui.model_manager import (
        build_diarization_config,
        is_speaker_model_downloaded,
    )

    if not is_speaker_model_downloaded(model_id):
        logger.warning("Speaker model %s not downloaded — no diarization", model_id)
        return None

    from roomkit.voice.pipeline.diarization.sherpa_onnx import (
        SherpaOnnxDiarizationProvider,
    )

    threshold = _coerce_threshold(settings.get("diarization_threshold", 0.4))
    diar_key = ("diar", model_id, inference_device, threshold)
    cached = engine._get_cached("diarization", diar_key)
    if cached is not None:
        diarization = cached
        reset_diarization(diarization)
        logger.info("Diarization: reusing cached %s", model_id)
    else:
        engine.loading_status.emit("Loading speaker model…")
        config = build_diarization_config(model_id, provider=inference_device, threshold=threshold)
        diarization = SherpaOnnxDiarizationProvider(config)
        engine._set_cached("diarization", diar_key, diarization)
    engine._diarization = diarization

    _enroll_speakers(diarization)
    _apply_primary_speaker_mode(engine, settings)

    logger.info(
        "Diarization: model=%s, threshold=%.2f, primary_mode=%s",
        model_id,
        threshold,
        engine._primary_speaker_mode,
    )
    return diarization


def _coerce_threshold(raw: Any) -> float:
    """Coerce a settings value to a float, falling back to 0.5 on bad input."""
    if isinstance(raw, str):
        try:
            return float(raw)
        except (ValueError, TypeError):
            return 0.5
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 0.5


def _enroll_speakers(diarization: Any) -> None:
    from roomkit_ui.speaker_manager import load_speakers

    for speaker in load_speakers():
        if speaker.embeddings:
            ok = diarization.register_speaker(speaker.name, speaker.embeddings)
            logger.info(
                "Enrolled speaker: %s (%d samples) → %s",
                speaker.name,
                len(speaker.embeddings),
                ok,
            )


def _apply_primary_speaker_mode(engine: Any, settings: dict) -> None:
    engine._primary_speaker_mode = settings.get("primary_speaker_mode", False)
    if engine._primary_speaker_mode:
        from roomkit_ui.speaker_manager import get_primary_speaker

        primary = get_primary_speaker()
        engine._primary_speaker_name = primary.name if primary else ""


# ---------------------------------------------------------------------------
# Attitude + user-visible error mapping
# ---------------------------------------------------------------------------


def resolve_attitude(settings: dict) -> str:
    """Resolve the selected attitude name to its text content."""
    name = settings.get("selected_attitude", "")
    if not name:
        return ""
    from roomkit_ui.constants import ATTITUDE_PRESETS

    for pname, ptext in ATTITUDE_PRESETS:
        if pname == name:
            return ptext
    try:
        for att in json.loads(settings.get("custom_attitudes", "[]")):
            if att.get("name") == name:
                return str(att.get("text", ""))
    except (json.JSONDecodeError, TypeError):
        pass
    return ""


def friendly_error(code: str, message: str) -> str:
    """Map raw provider errors to user-friendly messages."""
    low = f"{code} {message}".lower()
    if "1011" in low or "internal error" in low:
        return "Connection lost — the server closed unexpectedly. Try again."
    if "1006" in low or "abnormal" in low:
        return "Connection lost — network interruption."
    if "send_audio_failed" in low:
        return "Audio interrupted — please repeat."
    if "rate_limit" in low or "429" in low:
        return "Rate limited by the provider. Wait a moment and try again."
    if "auth" in low or "401" in low or "403" in low:
        return "Authentication failed — check your API key in Settings."
    return f"{code}: {message}"

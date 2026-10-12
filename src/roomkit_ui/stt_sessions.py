"""Dictation session bring-up mixin for :class:`roomkit_ui.stt_engine.STTEngine`.

Owns the provider-specific session construction (OpenAI Realtime, local
sherpa-onnx, Deepgram) — the lifecycle (toggle/stop/cleanup/paste) stays
in ``stt_engine.py``.  Like the ``Engine`` mixins, this class holds no
state: every attribute lives on the concrete ``STTEngine``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from roomkit_ui.constants import DICTATION_DETECTS
from roomkit_ui.dictation_stream import DictationStream
from roomkit_ui.engine_audio import local_audio_backend
from roomkit_ui.features import unavailable_reason
from roomkit_ui.model_manager import build_stt_config, is_model_downloaded, is_streaming_model

logger = logging.getLogger(__name__)


def dictation_unavailable(settings: dict) -> str:
    """Check the saved dictation setup without opening a provider or microphone."""
    provider = settings.get("stt_provider", "openai")
    feature = {"openai": "openai-realtime", "deepgram": "deepgram", "local": "local-voice"}.get(
        provider
    )
    if feature is None:
        return "Choose a speech recognition provider in Settings → Dictation."
    if reason := unavailable_reason(feature):
        return reason
    if provider == "local":
        model = settings.get("stt_model", "")
        if not model or not is_model_downloaded(model):
            return (
                "Download a speech model in Settings → Models & components, "
                "then select it in Dictation."
            )
    elif not str(settings.get(f"{provider}_api_key", "") or "").strip():
        name = "OpenAI" if provider == "openai" else "Deepgram"
        return f"Add your {name} key in Settings → Providers & keys to dictate a message."
    return ""


def dictation_language(settings: dict) -> str:
    """The language dictation transcribes: its own setting, else the spoken
    language (Settings → General).  "" means detected."""
    own = str(settings.get("dictation_language", "") or "")
    if own == DICTATION_DETECTS:
        return ""
    return own or str(settings.get("stt_language", "") or "")


class DictationSessionMixin:
    """Provider-specific session builders for ``STTEngine``.

    Each ``_start_*`` returns whether the session is up.  On failure it has
    already reported why and discarded what it opened; the lifecycle state
    is the engine's to restore.
    """

    _kit: Any
    _channel: Any
    _session: Any
    _provider: Any
    _transport: Any
    _accumulated_text: list[str]
    _local_provider: Any
    _local_backend: Any
    _local_session: Any
    _local_stream: DictationStream | None
    _cached_local_provider: Any
    _cached_local_key: tuple | None
    _batch_mode: bool
    _to_input: bool

    async def _start_openai_recording(self, settings: dict) -> bool:
        api_key = settings.get("openai_api_key", "")
        blocker = unavailable_reason("openai-realtime")
        if not blocker and not api_key:
            blocker = "OpenAI API key is required for dictation. Open Settings to enter it."
        if blocker:
            self._fail_start(blocker)  # type: ignore[attr-defined]
            return False

        try:
            from roomkit import RealtimeVoiceChannel, RoomKit
            from roomkit.providers.openai.realtime import OpenAIRealtimeProvider
            from roomkit.voice.backends.local import LocalAudioBackend

            self._kit = RoomKit()

            self._provider = OpenAIRealtimeProvider(
                api_key=api_key,
                model=settings.get("openai_model", "gpt-realtime-2.1"),
            )
            # A provider may finish after cancellation. Its callback belongs to
            # this capture, never to the draft that starts afterwards.
            accumulated = self._accumulated_text

            def on_transcription(session, text, role, is_final):
                if accumulated is self._accumulated_text:
                    self._on_transcription(session, text, role, is_final)

            self._provider.on_transcription(on_transcription)
            provider = self._provider

            sample_rate = 24000
            input_device = settings.get("input_device")

            transport = LocalAudioBackend(
                input_sample_rate=sample_rate,
                output_sample_rate=sample_rate,
                block_duration_ms=20,
                mute_mic_during_playback=False,
                input_device=input_device,
            )
            self._transport = transport

            self._channel = RealtimeVoiceChannel(
                "stt",
                provider=provider,
                transport=transport,
                input_sample_rate=sample_rate,
            )
            self._kit.register_channel(self._channel)

            await self._kit.create_room(room_id="stt-room")
            await self._kit.attach_channel("stt-room", "stt")

            self._session = await self._channel.start_session(
                "stt-room",
                "stt-user",
                connection=None,
                metadata={
                    "provider_config": {
                        "turn_detection_type": None if self._to_input else "server_vad",
                        "create_response": False,
                        "language": dictation_language(settings),
                    },
                },
            )

            logger.info(
                "Dictation started: provider=openai, model=%s, rate=%dHz",
                settings.get("openai_model", "gpt-realtime-2.1"),
                sample_rate,
            )
            return True

        except Exception as exc:
            logger.exception("Failed to start STT session")
            self._fail_start(str(exc))  # type: ignore[attr-defined]
            self._discard_session()  # type: ignore[attr-defined]
            return False

    # -- STT dictation (shared by local + Deepgram) ---------------------------

    async def _start_local_recording(self, settings: dict) -> bool:
        """Warm a Sherpa-Onnx model, then capture with its streaming/offline mode."""
        built = await self._build_local_stt(settings)
        if built is None:
            return False
        stt, batch_mode, log_extra = built
        return await self._start_vc_dictation(
            stt=stt,
            batch_mode=batch_mode,
            log_extra=log_extra,
            settings=settings,
            error_context="local",
        )

    async def _start_deepgram_recording(self, settings: dict) -> bool:
        """Deepgram streaming STT over RoomKit's LocalAudioBackend."""
        built = self._build_deepgram_stt(settings)
        if built is None:
            return False
        stt, batch_mode, log_extra = built
        return await self._start_vc_dictation(
            stt=stt,
            batch_mode=batch_mode,
            log_extra=log_extra,
            settings=settings,
            error_context="deepgram",
        )

    async def _build_local_stt(self, settings: dict) -> tuple[Any, bool, dict[str, str]] | None:
        """Build a Sherpa-Onnx STT provider. Returns ``(stt, batch_mode, log_extra)``
        or ``None`` after emitting a user-facing error."""
        model_id = settings.get("stt_model", "")
        unavailable = unavailable_reason("local-voice")
        if unavailable:
            self._fail_start(unavailable)
            return None
        if not model_id:
            self._fail_start(
                "No local STT model selected. Download one in Settings → Models & components, "
                "then select it in Dictation."
            )
            return None
        if not is_model_downloaded(model_id):
            self._fail_start(
                f"Model '{model_id}' is not downloaded. "
                "Download it in Settings → Models & components → Local models."
            )
            return None
        try:
            from roomkit.voice.stt.sherpa_onnx import SherpaOnnxSTTProvider
        except ImportError as exc:
            self._fail_start(
                f"Missing dependency for local STT: {exc}. Install with: pip install sherpa-onnx"
            )
            return None

        language = dictation_language(settings) or "en"
        translate = bool(settings.get("stt_translate", False))
        inference_device = settings.get("inference_device", "cpu")
        batch_mode = not is_streaming_model(model_id)
        key = (model_id, language, translate, inference_device)
        if self._cached_local_key == key:
            stt = self._cached_local_provider
        else:
            await self._close_cached_local_stt()
            config = build_stt_config(
                model_id, language, translate=translate, provider=inference_device
            )
            # Explicit EOF finishes a dictation; pauses must not reset its decoder.
            config.enable_endpoint_detection = False
            stt = SherpaOnnxSTTProvider(config)
            self._local_provider = stt  # Failed/cancelled warmup still owns cleanup.
            warmup = asyncio.create_task(stt.warmup())
            try:
                await asyncio.shield(warmup)
            except asyncio.CancelledError:
                # Native model loading cannot be cancelled; let it finish before
                # releasing the provider or allowing another capture to start.
                await warmup
                raise
            if not batch_mode:
                self._cached_local_key, self._cached_local_provider = key, stt
        log_extra = {
            "model": model_id,
            "mode": "batch" if batch_mode else "streaming",
            "task": "translate" if translate else "transcribe",
        }
        return stt, batch_mode, log_extra

    def _build_deepgram_stt(self, settings: dict) -> tuple[Any, bool, dict[str, str]] | None:
        """Build a Deepgram streaming STT provider. Returns ``(stt, False,
        log_extra)`` or ``None`` after emitting a user-facing error."""
        unavailable = unavailable_reason("deepgram")
        if unavailable:
            self._fail_start(unavailable)
            return None
        api_key = settings.get("deepgram_api_key", "")
        if not api_key:
            self._fail_start(
                "Deepgram API key is required for dictation. Open Settings to enter it."
            )
            return None
        try:
            from roomkit.voice.stt.deepgram import DeepgramConfig, DeepgramSTTProvider
        except ImportError as exc:
            self._fail_start(f"Missing dependency for Deepgram STT: {exc}.")
            return None

        language = dictation_language(settings) or "en"
        dg_config = DeepgramConfig(
            api_key=api_key,
            model=settings.get("deepgram_model", "nova-3"),
            language=language,
        )
        stt = DeepgramSTTProvider(dg_config)
        log_extra = {"model": dg_config.model, "language": language}
        # Deepgram is always streaming — no batch mode.
        return stt, False, log_extra

    async def _start_vc_dictation(
        self,
        *,
        stt: Any,
        batch_mode: bool,
        log_extra: dict[str, str],
        settings: dict,
        error_context: str,
    ) -> bool:
        """Open 16 kHz capture with a finite stream or an offline VoiceChannel.

        Failures during this phase emit an error signal and discard the
        partially opened session so a retry can start fresh.
        """
        try:
            if batch_mode:
                await self._open_vc_dictation_session(stt=stt, settings=settings)
            else:
                await self._open_streaming_dictation(stt=stt, settings=settings)
            extras = ", ".join(f"{k}={v}" for k, v in log_extra.items() if k != "mode")
            logger.info(
                "Dictation started: provider=%s, mode=%s, %s, rate=16000Hz",
                error_context,
                "batch" if batch_mode else "streaming",
                extras,
            )
        except Exception as exc:
            logger.exception("Failed to start %s STT session", error_context)
            self._fail_start(str(exc))  # type: ignore[attr-defined]
            self._discard_session()  # type: ignore[attr-defined]
            return False
        return True

    async def _open_streaming_dictation(self, *, stt: Any, settings: dict) -> None:
        """RoomKit capture → one provider stream whose input this app can finish."""
        self._local_provider = stt
        backend = self._dictation_backend(settings)
        self._local_backend = backend
        stream = DictationStream(stt, lambda error: self._stream_failed(stream, error))
        self._local_stream = stream
        backend.on_audio_received(stream.feed)
        self._local_session = await backend.connect("stt-room", "stt-user", "stt")
        await backend.start_listening(self._local_session)

    def _stream_failed(self, stream: DictationStream, error: str) -> None:
        if self._local_stream is stream:
            self._fail_start(error)
            self.cancel()

    @staticmethod
    def _dictation_backend(settings: dict) -> Any:
        return local_audio_backend(
            input_sample_rate=16000,
            output_sample_rate=16000,
            channels=1,
            block_duration_ms=20,
            input_device=settings.get("input_device"),
        )

    async def _open_vc_dictation_session(
        self,
        *,
        stt: Any,
        settings: dict,
    ) -> None:
        """Begin offline capture through a VoiceChannel with public flush_stt()."""
        from roomkit import (
            ChannelBinding,
            ChannelType,
            RoomKit,
            VoiceChannel,
        )
        from roomkit.voice.pipeline import AudioPipelineConfig

        self._local_provider = stt
        self._batch_mode = True

        # The session is opened below, not by attach_channel (auto_connect).
        backend = self._dictation_backend(settings)
        self._local_backend = backend

        voice = VoiceChannel(
            "stt",
            stt=stt,
            backend=backend,
            pipeline=AudioPipelineConfig(),
            batch_mode=True,
        )
        self._channel = voice

        kit = RoomKit()
        self._kit = kit
        kit.register_channel(voice)
        await kit.create_room(room_id="stt-room")
        await kit.attach_channel("stt-room", "stt")

        # Connect backend, bind session, start listening.
        self._local_session = await backend.connect("stt-room", "stt-user", "stt")
        binding = ChannelBinding(
            room_id="stt-room",
            channel_id="stt",
            channel_type=ChannelType.VOICE,
        )
        voice.bind_session(self._local_session, "stt-room", binding)
        await backend.start_listening(self._local_session)

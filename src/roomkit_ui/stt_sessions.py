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

from roomkit_ui.model_manager import build_stt_config, is_model_downloaded, is_streaming_model

logger = logging.getLogger(__name__)


class DictationSessionMixin:
    """Provider-specific session builders for ``STTEngine``."""

    _recording: bool
    _busy: bool
    _kit: Any
    _channel: Any
    _session: Any
    _provider: Any
    _transport: Any
    _accumulated_text: list[str]
    _local_provider: Any
    _local_backend: Any
    _local_session: Any
    _local_flush_event: asyncio.Event | None
    _batch_mode: bool

    async def _start_openai_recording(self, settings: dict) -> None:
        api_key = settings.get("openai_api_key", "")
        if not api_key:
            self.error_occurred.emit(  # type: ignore[attr-defined]
                "OpenAI API key is required for dictation. Open Settings to enter it."
            )
            self._recording = False
            self._busy = False
            self.recording_changed.emit(False)  # type: ignore[attr-defined]
            return

        try:
            from roomkit import RealtimeVoiceChannel, RoomKit
            from roomkit.providers.openai.realtime import OpenAIRealtimeProvider
            from roomkit.voice.backends.local import LocalAudioBackend

            self._kit = RoomKit()

            self._provider = OpenAIRealtimeProvider(
                api_key=api_key,
                model=settings.get("openai_model", "gpt-4o-realtime-preview"),
            )
            self._provider.on_transcription(self._on_transcription)
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
                        "turn_detection_type": "server_vad",
                        "create_response": False,
                    },
                },
            )

            # Set transcription language if configured.
            stt_language = settings.get("stt_language", "")
            if stt_language:
                await self._provider.send_event(
                    self._session,
                    {
                        "type": "session.update",
                        "session": {
                            "input_audio_transcription": {
                                "model": "gpt-4o-transcribe",
                                "language": stt_language,
                            },
                        },
                    },
                )
                logger.info("Set STT language: %s", stt_language)

            logger.info(
                "Dictation started: provider=openai, model=%s, rate=%dHz",
                settings.get("openai_model", "gpt-4o-realtime-preview"),
                sample_rate,
            )

        except Exception as exc:
            logger.exception("Failed to start STT session")
            self._recording = False
            self.recording_changed.emit(False)  # type: ignore[attr-defined]
            self.error_occurred.emit(str(exc))  # type: ignore[attr-defined]
            await self._cleanup()
        finally:
            self._busy = False

    # -- VoiceChannel dictation (shared by local + Deepgram) ------------------

    async def _start_local_recording(self, settings: dict) -> None:
        """Sherpa-Onnx STT via VoiceChannel + LocalAudioBackend."""
        built = self._build_local_stt(settings)
        if built is None:
            return
        stt, batch_mode, log_extra = built
        await self._start_vc_dictation(
            stt=stt,
            batch_mode=batch_mode,
            log_extra=log_extra,
            settings=settings,
            log_partials=True,
            error_context="local",
        )

    async def _start_deepgram_recording(self, settings: dict) -> None:
        """Deepgram streaming STT via VoiceChannel + LocalAudioBackend."""
        built = self._build_deepgram_stt(settings)
        if built is None:
            return
        stt, batch_mode, log_extra = built
        await self._start_vc_dictation(
            stt=stt,
            batch_mode=batch_mode,
            log_extra=log_extra,
            settings=settings,
            log_partials=False,
            error_context="deepgram",
        )

    def _build_local_stt(self, settings: dict) -> tuple[Any, bool, dict[str, str]] | None:
        """Build a Sherpa-Onnx STT provider. Returns ``(stt, batch_mode, log_extra)``
        or ``None`` after emitting a user-facing error."""
        model_id = settings.get("stt_model", "")
        if not model_id:
            self._fail_start(
                "No local STT model selected. Go to Settings → AI Models to choose one."
            )
            return None
        if not is_model_downloaded(model_id):
            self._fail_start(
                f"Model '{model_id}' is not downloaded. Go to Settings → AI Models to download it."
            )
            return None
        try:
            from roomkit.voice.stt.sherpa_onnx import SherpaOnnxSTTProvider
        except ImportError as exc:
            self._fail_start(
                f"Missing dependency for local STT: {exc}. Install with: pip install sherpa-onnx"
            )
            return None

        language = settings.get("stt_language", "") or "en"
        translate = bool(settings.get("stt_translate", False))
        inference_device = settings.get("inference_device", "cpu")
        config = build_stt_config(
            model_id, language, translate=translate, provider=inference_device
        )
        # Dictation: the user controls start/stop, so disable endpoint
        # detection — we get one final result on flush instead of splitting
        # the transcription into segments at pauses.
        config.enable_endpoint_detection = False
        stt = SherpaOnnxSTTProvider(config)
        batch_mode = not is_streaming_model(model_id)
        log_extra = {
            "model": model_id,
            "mode": "batch" if batch_mode else "streaming",
            "task": "translate" if translate else "transcribe",
        }
        return stt, batch_mode, log_extra

    def _build_deepgram_stt(self, settings: dict) -> tuple[Any, bool, dict[str, str]] | None:
        """Build a Deepgram streaming STT provider. Returns ``(stt, False,
        log_extra)`` or ``None`` after emitting a user-facing error."""
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

        language = settings.get("stt_language", "") or "en"
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
        log_partials: bool,
        error_context: str,
    ) -> None:
        """Shared VoiceChannel session bring-up for dictation.

        Creates the 16 kHz ``LocalAudioBackend``, wraps the STT provider in
        a ``VoiceChannel``, registers the transcription hook, then wires
        the session via ``backend.connect`` → ``bind_session`` →
        ``start_listening``.

        Failures during this phase emit an error signal, run the partial
        cleanup (``_cleanup_local``) and reset recording state so a retry
        can start fresh.  The ``finally`` block always drops the busy flag.
        """
        try:
            await self._open_vc_dictation_session(
                stt=stt,
                batch_mode=batch_mode,
                settings=settings,
                log_partials=log_partials,
                log_extra=log_extra,
                provider_label=error_context,
            )
        except Exception as exc:
            logger.exception("Failed to start %s STT session", error_context)
            self.error_occurred.emit(str(exc))  # type: ignore[attr-defined]
            self._cleanup_local()
            self._recording = False
            self.recording_changed.emit(False)  # type: ignore[attr-defined]
        finally:
            self._busy = False

    async def _open_vc_dictation_session(
        self,
        *,
        stt: Any,
        batch_mode: bool,
        settings: dict,
        log_partials: bool,
        log_extra: dict[str, str],
        provider_label: str,
    ) -> None:
        """Create the VoiceChannel + backend + hooks and begin listening."""
        from roomkit import (
            ChannelBinding,
            ChannelType,
            HookExecution,
            HookResult,
            HookTrigger,
            RoomKit,
            VoiceChannel,
        )
        from roomkit.voice.backends.local import LocalAudioBackend
        from roomkit.voice.pipeline import AudioPipelineConfig

        self._local_provider = stt
        self._batch_mode = batch_mode

        backend = LocalAudioBackend(
            input_sample_rate=16000,
            output_sample_rate=16000,
            channels=1,
            block_duration_ms=20,
            input_device=settings.get("input_device"),
        )
        self._local_backend = backend

        voice = VoiceChannel(
            "stt",
            stt=stt,
            backend=backend,
            pipeline=AudioPipelineConfig(),
            batch_mode=batch_mode,
        )
        self._channel = voice

        kit = RoomKit()
        self._kit = kit
        kit.register_channel(voice)
        await kit.create_room(room_id="stt-room")
        await kit.attach_channel("stt-room", "stt")

        # Hooks: streaming mode only.  Batch mode flushes on stop via
        # channel.flush_stt(), so no hook is needed during capture.
        if not batch_mode:
            accumulated = self._accumulated_text
            self._local_flush_event = asyncio.Event()
            flush_event = self._local_flush_event

            if log_partials:

                @kit.hook(
                    HookTrigger.ON_PARTIAL_TRANSCRIPTION,
                    execution=HookExecution.ASYNC,
                )
                async def _on_partial(result, ctx):
                    logger.info("%s STT partial: %s", provider_label, result.text)

            @kit.hook(HookTrigger.ON_TRANSCRIPTION)
            async def _on_transcription(event, ctx):
                # roomkit 0.10.0 passes a TranscriptionEvent (with .text),
                # not the raw string it used to hand ON_TRANSCRIPTION hooks.
                text = event.text
                if text and text.strip():
                    logger.info("%s STT final: %s", provider_label, text)
                    accumulated.append(text.strip())
                flush_event.set()
                return HookResult.block("dictation-only")

        # Connect backend, bind session, start listening.
        self._local_session = await backend.connect("stt-room", "stt-user", "stt")
        binding = ChannelBinding(
            room_id="stt-room",
            channel_id="stt",
            channel_type=ChannelType.VOICE,
        )
        voice.bind_session(self._local_session, "stt-room", binding)
        await backend.start_listening(self._local_session)

        extras = ", ".join(f"{k}={v}" for k, v in log_extra.items())
        logger.info(
            "Dictation started: provider=%s, %s, rate=16000Hz",
            provider_label,
            extras,
        )

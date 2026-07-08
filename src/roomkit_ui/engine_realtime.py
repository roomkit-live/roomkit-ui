"""Realtime speech-to-speech session mixin for ``Engine``.

Contains the Gemini-Live / OpenAI-Realtime startup path: build the
provider, wire audio pipeline + transport, connect MCP tools, register
hooks, and hand off to the UI by populating ``engine._session``.

The 2-step retry (with → without MCP tools) stays intact so providers
that reject the MCP schema still deliver a working session.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from roomkit_ui.builtin_tools import BUILTIN_TOOLS
from roomkit_ui.engine_audio import (
    build_audio_processing,
    build_debug_taps,
    build_recorder,
    resolve_attitude,
    setup_diarization,
)
from roomkit_ui.engine_state import EngineState
from roomkit_ui.hooks import register_realtime_hooks

logger = logging.getLogger(__name__)


class RealtimeMixin:
    """Realtime (speech-to-speech) session setup for ``Engine``.

    Attribute annotations mirror the concrete ``Engine`` so mypy can type
    ``self._attitude`` and friends from inside mixin methods.
    """

    _state: EngineState
    _attitude: str
    _attitude_name: str
    _base_system_prompt: str
    _diarization: Any
    _primary_speaker_mode: bool
    _primary_speaker_name: str
    _transport: Any
    _kit: Any
    _channel: Any
    _session: Any
    _pending_tool_calls: int

    async def _start_realtime(self, settings: dict) -> None:
        self._set_state(EngineState.CONNECTING)  # type: ignore[attr-defined]

        try:
            provider_name = settings.get("provider", "gemini")
            base_prompt = settings.get(
                "system_prompt",
                "You are a friendly voice assistant. Be concise and helpful.",
            )
            # Cache the user's base prompt (without attitude) so the
            # set_attitude tool can recompute the full prompt and push it
            # via RealtimeVoiceChannel.reconfigure_session() mid-session.
            self._base_system_prompt = base_prompt  # type: ignore[attr-defined]
            system_prompt = base_prompt
            attitude = self._attitude or resolve_attitude(settings)
            if attitude:
                system_prompt = f"{system_prompt}\n\n# Attitude\n{attitude}"
                self._attitude = attitude
                if not self._attitude_name:
                    self._attitude_name = settings.get("selected_attitude", "") or attitude
            aec_mode = settings.get("aec_mode", "webrtc")

            from roomkit import RealtimeVoiceChannel, RoomKit
            from roomkit.voice.backends.local import LocalAudioBackend

            provider, voice, model = _build_realtime_provider(provider_name, settings)
            provider_config = _build_provider_config(provider_name, settings)

            sample_rate = 24000
            block_ms = 20
            frame_size = sample_rate * block_ms // 1000

            # Denoisers are voice-channel only: a speech enhancer on the mic
            # path keeps the *dominant* voice, so during doubletalk it eats
            # the user's barge-in speech before the provider's VAD sees it.
            aec, _ = build_audio_processing(aec_mode, "none", sample_rate, frame_size)
            denoise_mode = settings.get("denoise", "none")
            if denoise_mode != "none":
                logger.info("Denoiser (%s) not applied in realtime mode", denoise_mode)
            mute_mic = aec is None

            input_device = settings.get("input_device")
            output_device = settings.get("output_device")

            # -- Diarization (optional; requires VAD) -----------------------------
            # Realtime only needs a VAD when diarization is requested — build it
            # conditionally so non-diarization sessions don't load the model.
            inference_device = settings.get("inference_device", "cpu")
            vad = None
            if settings.get("diarization_enabled") and settings.get("diarization_model"):
                vad = _build_realtime_vad(settings)
            diarization = setup_diarization(
                self, settings, vad_available=vad is not None, inference_device=inference_device
            )
            if settings.get("diarization_enabled") and diarization is None:
                self.session_notice.emit(  # type: ignore[attr-defined]
                    "Speaker diarization is inactive for this session — it needs both "
                    "a speaker model and a VAD model (Settings → AI Models)."
                )

            debug_taps = build_debug_taps(settings)
            recorder, recording_config = build_recorder(settings)

            pipeline = _build_realtime_pipeline(
                diarization=diarization,
                vad=vad,
                aec=aec,
                debug_taps=debug_taps,
                recorder=recorder,
                recording_config=recording_config,
                sample_rate=sample_rate,
            )

            # -- Transport -------------------------------------------------------
            # Pipeline attaches to the RealtimeVoiceChannel (see _start_session),
            # NOT the transport.  AEC deliberately does NOT go to the backend:
            # LocalAudioBackend(aec=...) flags NATIVE_AEC, which makes the
            # pipeline skip its AEC stage and lose the continuous playback
            # reference (the 0.9.0 barge-in fix).  Same wiring as roomkit's
            # examples/realtime_voice_local_gemini.py.
            transport = LocalAudioBackend(
                input_sample_rate=sample_rate,
                output_sample_rate=sample_rate,
                block_duration_ms=block_ms,
                mute_mic_during_playback=mute_mic,
                input_device=input_device,
                output_device=output_device,
            )

            self._transport = transport  # type: ignore[attr-defined]

            # Register speaker change callback on the transport so the engine
            # can gate audio on non-primary speakers.  The pipeline instance
            # that actually produces SPEAKER_CHANGE events is owned by the
            # channel, but the transport forwards pipeline callbacks when
            # the channel is bound.
            if pipeline is not None:
                transport.on_speaker_change(self._on_transport_speaker_change)  # type: ignore[attr-defined]

            aec_label = type(aec).__name__ if aec else "none"
            logger.info(
                "Audio pipeline: aec=%s (pipeline stage), rate=%dHz, block=%dms",
                aec_label,
                sample_rate,
                block_ms,
            )

            self._register_callbacks(provider, transport)  # type: ignore[attr-defined]

            # -- MCP tools -------------------------------------------------------
            mcp_servers_configured = False
            try:
                mcp_servers_configured = any(
                    s.get("enabled", True) for s in json.loads(settings.get("mcp_servers", "[]"))
                )
            except (json.JSONDecodeError, TypeError):
                pass
            if mcp_servers_configured:
                self.loading_status.emit("Connecting MCP servers…")  # type: ignore[attr-defined]
            tools, has_mcp_tools = await self._setup_mcp_tools(settings)  # type: ignore[attr-defined]
            tool_handler = self._handle_tool_call  # type: ignore[attr-defined]

            all_names = ", ".join(t["name"] for t in tools)
            logger.info("Tools: %s", all_names)

            self.loading_status.emit("Connecting to provider…")  # type: ignore[attr-defined]
            if provider_config:
                logger.debug("provider_config: %s", provider_config)
            self._session = await self._start_session(  # type: ignore[attr-defined]
                RoomKit,
                RealtimeVoiceChannel,
                provider,
                transport,
                system_prompt,
                voice,
                sample_rate,
                tools,
                tool_handler,
                provider_config=provider_config or None,
                settings=settings,
                pipeline=pipeline,
            )
            if self._session is None and has_mcp_tools:  # type: ignore[attr-defined]
                # MCP tools broke the session — retry without them
                logger.warning("Retrying session without MCP tools")
                self._session = await self._start_session(  # type: ignore[attr-defined]
                    RoomKit,
                    RealtimeVoiceChannel,
                    provider,
                    transport,
                    system_prompt,
                    voice,
                    sample_rate,
                    list(BUILTIN_TOOLS),
                    tool_handler,
                    provider_config=provider_config or None,
                    settings=settings,
                    pipeline=pipeline,
                )
                if self._session is not None:  # type: ignore[attr-defined]
                    self.mcp_status.emit(  # type: ignore[attr-defined]
                        "MCP tools disabled — incompatible with this provider"
                    )
                    tools = list(BUILTIN_TOOLS)

            if self._session is None:  # type: ignore[attr-defined]
                raise RuntimeError("Failed to start voice session")

            register_realtime_hooks(self._kit, self)  # type: ignore[attr-defined]

            self._spk_rms_queue.clear()  # type: ignore[attr-defined]
            self._spk_timer.start()  # type: ignore[attr-defined]
            self._pending_tool_calls = 0  # type: ignore[attr-defined]
            self._watchdog.start()  # type: ignore[attr-defined]

            self._set_state(EngineState.ACTIVE)  # type: ignore[attr-defined]

            # Emit structured session info for the UI info bar
            tool_info = [
                {"name": t.get("name", ""), "description": t.get("description", "")} for t in tools
            ]
            info: dict = {
                "provider": provider_name,
                "model": model,
                "tools": tool_info,
            }
            if self._mcp and self._mcp.failed_servers:  # type: ignore[attr-defined]
                info["failed_servers"] = list(self._mcp.failed_servers)  # type: ignore[attr-defined]
            self.session_info.emit(info)  # type: ignore[attr-defined]
            if self._attitude_name:  # type: ignore[attr-defined]
                self.attitude_changed.emit(self._attitude_name)  # type: ignore[attr-defined]

        except Exception as e:
            logger.exception("Failed to start voice session")
            self._set_state(EngineState.ERROR)  # type: ignore[attr-defined]
            self.error_occurred.emit(str(e))  # type: ignore[attr-defined]
            await self._cleanup()  # type: ignore[attr-defined]

    async def _start_session(
        self,
        RoomKit: type,  # noqa: N803
        RealtimeVoiceChannel: type,  # noqa: N803
        provider: Any,
        transport: Any,
        system_prompt: str,
        voice: str,
        sample_rate: int,
        tools: list[dict],
        tool_handler: Any,
        provider_config: dict[str, Any] | None = None,
        settings: dict | None = None,
        pipeline: Any = None,
    ) -> Any:
        """Try to create a room and start a realtime session.  Returns None on failure."""
        from roomkit_ui.engine_audio import build_telemetry

        try:
            telemetry = build_telemetry(settings) if settings else None
            self._kit = RoomKit(telemetry=telemetry)  # type: ignore[attr-defined]
            self._channel = RealtimeVoiceChannel(  # type: ignore[attr-defined]
                "voice",
                provider=provider,
                transport=transport,
                system_prompt=system_prompt,
                voice=voice,
                input_sample_rate=sample_rate,
                tools=tools,
                tool_handler=tool_handler,
                pipeline=pipeline,
            )
            self._kit.register_channel(self._channel)  # type: ignore[attr-defined]
            await self._kit.create_room(room_id="local-demo")  # type: ignore[attr-defined]
            await self._kit.attach_channel("local-demo", "voice")  # type: ignore[attr-defined]
            metadata = {"provider_config": provider_config} if provider_config else None
            return await self._channel.start_session(  # type: ignore[attr-defined]
                "local-demo",
                "local-user",
                connection=None,
                metadata=metadata,
            )
        except Exception:
            logger.exception("_start_session failed")
            try:
                await self._kit.close()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._kit = None  # type: ignore[attr-defined]
            self._channel = None  # type: ignore[attr-defined]
            return None


# ---------------------------------------------------------------------------
# Provider construction helpers (module-level — no engine state)
# ---------------------------------------------------------------------------


def _build_realtime_provider(provider_name: str, settings: dict) -> tuple[Any, str, str]:
    """Instantiate the realtime provider. Returns (provider, voice, model)."""
    if provider_name == "openai":
        api_key = settings.get("openai_api_key", "")
        if not api_key:
            raise ValueError("OpenAI API key is required. Open Settings to enter it.")
        model = settings.get("openai_model", "gpt-4o-realtime-preview")
        voice = settings.get("openai_voice", "alloy")
        from roomkit.providers.openai.realtime import OpenAIRealtimeProvider

        return OpenAIRealtimeProvider(api_key=api_key, model=model), voice, model

    api_key = settings.get("api_key", "")
    if not api_key:
        raise ValueError("Google API key is required. Open Settings to enter it.")
    model = settings.get("model", "gemini-2.5-flash-native-audio-preview-12-2025")
    voice = settings.get("voice", "Aoede")
    from roomkit.providers.gemini.realtime import GeminiLiveProvider

    return GeminiLiveProvider(api_key=api_key, model=model), voice, model


def _build_provider_config(provider_name: str, settings: dict) -> dict[str, Any]:
    """Assemble provider-specific advanced settings (VAD, proactive audio, etc.)."""
    provider_config: dict[str, Any] = {}
    if provider_name == "gemini":
        lang = settings.get("gemini_language", "")
        if lang:
            provider_config["language"] = lang
        if settings.get("gemini_no_interruption"):
            provider_config["no_interruption"] = True
        # enable_affective_dialog: not yet supported by the Gemini API
        # (serialized under generation_config, rejected with 1007).
        # Uncomment when the API adds support.
        # if settings.get("gemini_affective_dialog"):
        #     provider_config["enable_affective_dialog"] = True
        if settings.get("gemini_proactive_audio"):
            provider_config["proactive_audio"] = True
        start_sens = settings.get("gemini_start_sensitivity", "")
        if start_sens:
            provider_config["start_of_speech_sensitivity"] = start_sens
        end_sens = settings.get("gemini_end_sensitivity", "")
        if end_sens:
            provider_config["end_of_speech_sensitivity"] = end_sens
        silence_ms = settings.get("gemini_silence_duration_ms", "")
        if silence_ms:
            try:
                provider_config["silence_duration_ms"] = int(silence_ms)
            except (ValueError, TypeError):
                pass
    elif provider_name == "openai":
        td_type = settings.get("openai_turn_detection", "server_vad")
        if td_type in ("server_vad", "semantic_vad"):
            provider_config["turn_detection_type"] = td_type
            if td_type == "semantic_vad":
                _apply_openai_semantic_vad(provider_config, settings)
            elif td_type == "server_vad":
                _apply_openai_server_vad(provider_config, settings)
            if not settings.get("openai_interrupt_response", True):
                provider_config["interrupt_response"] = False
            if not settings.get("openai_create_response", True):
                provider_config["create_response"] = False
        else:
            # "none" — disable turn detection entirely
            provider_config["turn_detection_type"] = None
    return provider_config


def _apply_openai_semantic_vad(provider_config: dict[str, Any], settings: dict) -> None:
    eagerness = settings.get("openai_eagerness", "")
    if eagerness:
        try:
            provider_config["eagerness"] = float(eagerness)
        except (ValueError, TypeError):
            pass


def _apply_openai_server_vad(provider_config: dict[str, Any], settings: dict) -> None:
    threshold = settings.get("openai_vad_threshold", "")
    if threshold:
        try:
            provider_config["threshold"] = float(threshold)
        except (ValueError, TypeError):
            pass
    silence_ms = settings.get("openai_silence_duration_ms", "")
    if silence_ms:
        try:
            provider_config["silence_duration_ms"] = int(silence_ms)
        except (ValueError, TypeError):
            pass
    prefix_ms = settings.get("openai_prefix_padding_ms", "")
    if prefix_ms:
        try:
            provider_config["prefix_padding_ms"] = int(prefix_ms)
        except (ValueError, TypeError):
            pass


# ---------------------------------------------------------------------------
# Pipeline / VAD helpers (module-level — no engine state)
# ---------------------------------------------------------------------------


def _build_realtime_vad(settings: dict) -> Any:
    """Build a VAD provider for realtime diarization, or ``None`` if unavailable."""
    vad_model_id = settings.get("vc_vad_model", "")
    if not vad_model_id:
        return None

    from roomkit_ui.model_manager import build_vad_config, is_vad_model_downloaded

    if not is_vad_model_downloaded(vad_model_id):
        logger.warning("VAD model %s not downloaded — no VAD", vad_model_id)
        return None

    from roomkit.voice.pipeline.vad.sherpa_onnx import SherpaOnnxVADProvider

    inference_device = settings.get("inference_device", "cpu")
    vad_config = build_vad_config(vad_model_id, provider=inference_device, settings=settings)
    logger.info("Realtime VAD: %s", vad_model_id)
    return SherpaOnnxVADProvider(vad_config)


def _build_realtime_pipeline(
    *,
    diarization: Any,
    vad: Any,
    aec: Any,
    debug_taps: Any,
    recorder: Any,
    recording_config: Any,
    sample_rate: int,
) -> Any:
    """Assemble the realtime ``AudioPipelineConfig`` (or ``None`` if nothing to do).

    Diarization + VAD get wired together with a 24 kHz→16 kHz contract because
    realtime providers stream at 24 kHz but the VAD / diarization models are
    16 kHz-only.  Other stages (AEC, debug taps, recorder) attach at the
    transport's native sample rate.  No denoiser in realtime — see
    ``_start_realtime``.
    """
    from roomkit.voice.pipeline.config import AudioPipelineConfig

    if diarization is not None and vad is not None:
        from roomkit.voice.pipeline.config import AudioFormat, AudioPipelineContract

        contract = AudioPipelineContract(
            transport_inbound_format=AudioFormat(sample_rate=sample_rate),
            internal_format=AudioFormat(sample_rate=16000),
        )
        return AudioPipelineConfig(
            aec=aec,
            vad=vad,
            diarization=diarization,
            contract=contract,
            debug_taps=debug_taps,
            recorder=recorder,
            recording_config=recording_config,
        )

    if aec is not None or debug_taps is not None or recorder is not None:
        return AudioPipelineConfig(
            aec=aec,
            debug_taps=debug_taps,
            recorder=recorder,
            recording_config=recording_config,
        )
    return None

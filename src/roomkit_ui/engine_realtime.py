"""Realtime speech-to-speech session mixin for ``Engine``.

Contains the realtime startup path (Gemini Live, OpenAI Realtime,
Deepgram Voice Agent, ElevenLabs Conversational AI, xAI Grok): build the
provider, wire audio pipeline + transport, connect MCP tools, register
hooks, and hand off to the UI by populating ``engine._session``.

The 2-step retry (with → without MCP tools) stays intact so providers
that reject the MCP schema still deliver a working session.
"""

from __future__ import annotations

import logging
from typing import Any

from roomkit_ui.engine_audio import (
    DSP_THREADS,
    build_audio_processing,
    build_debug_taps,
    build_recorder,
    resolve_attitude,
    setup_diarization,
)
from roomkit_ui.engine_state import EngineState
from roomkit_ui.hooks import register_realtime_hooks
from roomkit_ui.mcp_config import has_enabled_mcp_servers
from roomkit_ui.toolset import tool_summaries

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

            sample_rate = _realtime_sample_rate(provider_name)
            block_ms = 20
            frame_size = sample_rate * block_ms // 1000

            # User-selected denoisers are voice-channel only: a speech
            # enhancer on the mic path keeps the *dominant* voice, so during
            # doubletalk it eats the user's barge-in speech before the
            # provider's VAD sees it.  (Deepgram gets the mild WebRTC noise
            # suppressor below, mirroring roomkit's example.)
            #
            # Half-duplex (Deepgram escape hatch): the mic is muted while
            # the agent speaks, so there is no echo to cancel — skip the AEC
            # and let `mute_mic = aec is None` below arm the playback gate.
            if _deepgram_half_duplex(provider_name, settings):
                logger.info("Deepgram half-duplex: mic muted during playback, AEC skipped")
                aec_mode = "none"
            aec, _ = build_audio_processing(aec_mode, "none", sample_rate, frame_size)

            # AEC bench capture (ROOMKIT_AEC_DUMP=<dir>): realtime-only —
            # the VC path hands the same AEC instance to the backend, whose
            # transport-level integration the recorder does not mimic.
            import os

            dump_dir = os.environ.get("ROOMKIT_AEC_DUMP", "")
            if aec is not None and dump_dir:
                from pathlib import Path

                from roomkit_ui.aec_dump import AECDumpRecorder

                aec = AECDumpRecorder(aec, Path(dump_dir).expanduser())
                logger.warning("AEC dump recording enabled → %s", dump_dir)
            denoise_mode = settings.get("denoise", "none")
            if denoise_mode != "none":
                logger.info("Denoiser (%s) not applied in realtime mode", denoise_mode)
            mute_mic = aec is None

            # Provider-specific transport wiring — see _transport_audio_profile.
            transport_aec, rt_denoiser, prebuffer_ms = _transport_audio_profile(
                provider_name, aec, sample_rate
            )
            if transport_aec is not None:
                logger.info(
                    "Transport-level AEC (%s) + webrtc NS, prebuffer=%dms",
                    provider_name,
                    prebuffer_ms,
                )

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
                denoiser=rt_denoiser,
                debug_taps=debug_taps,
                recorder=recorder,
                recording_config=recording_config,
                sample_rate=sample_rate,
            )

            # -- Transport -------------------------------------------------------
            # Pipeline attaches to the RealtimeVoiceChannel (see _start_session),
            # NOT the transport.  AEC placement is per provider (see
            # _transport_audio_profile): Gemini/OpenAI keep the pipeline-stage
            # AEC (transport_aec is None — LocalAudioBackend(aec=...) would
            # flag NATIVE_AEC and lose the continuous playback reference, the
            # 0.9.0 barge-in fix), while Deepgram runs it at transport level
            # like roomkit's examples/realtime_voice_local_deepgram.py, where
            # NATIVE_AEC correctly makes the pipeline skip its own stage.
            transport = LocalAudioBackend(
                input_sample_rate=sample_rate,
                output_sample_rate=sample_rate,
                block_duration_ms=block_ms,
                mute_mic_during_playback=mute_mic,
                rt_prebuffer_ms=prebuffer_ms,
                input_device=input_device,
                output_device=output_device,
                aec=transport_aec,
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
            if has_enabled_mcp_servers(settings.get("mcp_servers", "[]")):
                self.loading_status.emit("Connecting MCP servers…")  # type: ignore[attr-defined]
            toolset = await self._setup_tools(settings)  # type: ignore[attr-defined]
            tools = toolset.all
            tool_handler = self._handle_tool_call  # type: ignore[attr-defined]

            # Agent Skills — same registry the VC path loads.  The channel
            # resolves delivery per provider: reconfigurable sessions (Gemini,
            # OpenAI) get the skill list in the prompt plus an activate_skill
            # tool; fixed sessions get every body inlined at connect.
            skills_registry = self._load_skills(settings)  # type: ignore[attr-defined]

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
                skills=skills_registry,
            )
            if self._session is None and toolset.has_mcp:  # type: ignore[attr-defined]
                # MCP tools broke the session — retry without them. Only MCP is
                # shed: its schemas are server-supplied and arbitrary, whereas
                # built-in and CLI schemas are hand-authored and known-good.
                logger.warning("Retrying session without MCP tools")
                self._session = await self._start_session(  # type: ignore[attr-defined]
                    RoomKit,
                    RealtimeVoiceChannel,
                    provider,
                    transport,
                    system_prompt,
                    voice,
                    sample_rate,
                    toolset.without_mcp,
                    tool_handler,
                    provider_config=provider_config or None,
                    settings=settings,
                    pipeline=pipeline,
                    skills=skills_registry,
                )
                if self._session is not None:  # type: ignore[attr-defined]
                    self.mcp_status.emit(  # type: ignore[attr-defined]
                        "MCP tools disabled — incompatible with this provider"
                    )
                    tools = toolset.without_mcp

            if self._session is None:  # type: ignore[attr-defined]
                raise RuntimeError("Failed to start voice session")

            register_realtime_hooks(self._kit, self)  # type: ignore[attr-defined]

            self._spk_rms_queue.clear()  # type: ignore[attr-defined]
            self._spk_timer.start()  # type: ignore[attr-defined]
            self._pending_tool_calls = 0  # type: ignore[attr-defined]
            self._watchdog.start()  # type: ignore[attr-defined]

            self._set_state(EngineState.ACTIVE)  # type: ignore[attr-defined]

            # Emit structured session info for the UI info bar
            skill_info: list[dict] = []
            if skills_registry and skills_registry.skill_count > 0:
                skill_info = [
                    {"name": m.name, "description": m.description}
                    for m in skills_registry.all_metadata()
                ]
            info: dict = {
                "provider": provider_name,
                "model": model,
                "tools": tool_summaries(tools),
                "skills": skill_info,
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
        skills: Any = None,
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
                # ElevenLabs has no per-session voice override (agent-defined) —
                # its builder returns "" and the channel must see None.
                voice=voice or None,
                input_sample_rate=sample_rate,
                output_sample_rate=sample_rate,
                tools=tools,
                tool_handler=tool_handler,
                pipeline=pipeline,
                skills=skills,
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


def _realtime_sample_rate(provider_name: str) -> int:
    """Transport sample rate for a realtime provider.

    ElevenLabs ConvAI runs a fixed 16 kHz contract on both legs (roomkit
    raises on anything else); every other provider streams 24 kHz PCM.
    """
    return 16000 if provider_name == "elevenlabs" else 24000


def _build_realtime_provider(provider_name: str, settings: dict) -> tuple[Any, str, str]:
    """Instantiate the realtime provider. Returns (provider, voice, model).

    ``voice`` may be ``""`` (ElevenLabs — the agent defines it); callers must
    map that to ``None`` before handing it to the channel.
    """
    if provider_name == "openai":
        api_key = settings.get("openai_api_key", "")
        if not api_key:
            raise ValueError("OpenAI API key is required. Open Settings to enter it.")
        model = settings.get("openai_model", "gpt-realtime-2.1")
        voice = settings.get("openai_voice", "alloy")
        from roomkit.providers.openai.realtime import OpenAIRealtimeProvider

        return OpenAIRealtimeProvider(api_key=api_key, model=model), voice, model

    if provider_name == "deepgram":
        return _build_deepgram_agent(settings)

    if provider_name == "elevenlabs":
        return _build_elevenlabs_realtime(settings)

    if provider_name == "xai":
        return _build_xai_realtime(settings)

    api_key = settings.get("api_key", "")
    if not api_key:
        raise ValueError("Google API key is required. Open Settings to enter it.")
    model = settings.get("model", "gemini-2.5-flash-native-audio-preview-12-2025")
    voice = settings.get("voice", "Aoede")
    from roomkit.providers.gemini.realtime import GeminiLiveProvider

    return GeminiLiveProvider(api_key=api_key, model=model), voice, model


def _deepgram_listen_stage(settings: dict) -> tuple[str, str | None, str | None]:
    """Resolve (listen_model, listen_version, listen_language) from settings.

    Derivations instead of rejections: nova-3 monolingual is English-only,
    so a specific language with no explicit model selects nova-2; the Flux
    models require the ``v2`` listen API version, so it is set whenever a
    flux model is chosen.
    """
    model = (settings.get("deepgram_agent_listen_model", "") or "").strip()
    language = (settings.get("deepgram_agent_listen_language", "") or "").strip() or None
    if not model:
        model = "nova-2" if language and language not in ("en", "multi") else "nova-3"
        if model == "nova-2":
            logger.info("Deepgram listen model derived: nova-2 (language=%s)", language)
    version = "v2" if model.startswith("flux") else None
    return model, version, language


def _deepgram_half_duplex(provider_name: str, settings: dict) -> bool:
    """Whether this session should mute the mic during agent playback.

    Deepgram owns turn detection outright (``server_vad=False`` is ignored)
    and exposes no sensitivity knob.  With the example-mirroring transport
    AEC the mic stays open by default; this remains the escape hatch for
    setups whose echo still trips it (loud speakers, no AEC installed).
    """
    return provider_name == "deepgram" and bool(settings.get("deepgram_agent_half_duplex", False))


def _transport_audio_profile(
    provider_name: str, aec: Any, sample_rate: int
) -> tuple[Any, Any, int]:
    """Per-provider transport wiring: (transport_aec, pipeline_denoiser, prebuffer_ms).

    Deepgram mirrors roomkit's ``examples/realtime_voice_local_deepgram.py``:
    the AEC runs at transport level — inline on the PortAudio thread, so
    reference and capture stay sample-synchronous.  Deepgram's turn
    detection cannot tell the agent's echo from the caller, and the example
    documents the endless barge-in loop an open, poorly-aligned mic causes.
    A WebRTC noise suppressor rides the pipeline and the playback prebuffer
    grows to absorb Aura's bursty delivery (the mid-response underruns seen
    in the field logs).  Gemini/OpenAI keep the pipeline-stage AEC,
    mirroring ``examples/realtime_voice_local_gemini.py``.
    """
    if provider_name == "deepgram" and aec is not None:
        from roomkit_ui.engine_audio import build_denoiser

        return aec, build_denoiser("webrtc", sample_rate), 240
    return None, None, 120


def _build_deepgram_agent(settings: dict) -> tuple[Any, str, str]:
    """Deepgram composes the agent from listen/think/speak stages."""
    api_key = settings.get("deepgram_api_key", "")
    if not api_key:
        raise ValueError("Deepgram API key is required. Open Settings to enter it.")
    voice = settings.get("deepgram_agent_voice", "") or "aura-2-thalia-en"
    think_provider = settings.get("deepgram_agent_think_provider", "") or "open_ai"
    think_model = settings.get("deepgram_agent_think_model", "")
    if not think_model:
        if think_provider != "open_ai":
            # gpt-4o-mini is Deepgram's default for open_ai only — sending it
            # with another think provider is an invalid pairing Deepgram
            # rejects mid-handshake, far less legibly than this.
            raise ValueError(
                f"Deepgram think model is required for the {think_provider} LLM "
                "provider. Open Settings → Advanced to pick one."
            )
        think_model = "gpt-4o-mini"
    listen_model, listen_version, listen_language = _deepgram_listen_stage(settings)

    from roomkit.providers.deepgram.config import DeepgramAgentConfig
    from roomkit.providers.deepgram.realtime import DeepgramAgentProvider

    config = DeepgramAgentConfig(
        api_key=api_key,
        listen_model=listen_model,
        listen_version=listen_version,
        listen_language=listen_language,
        think_provider=think_provider,
        think_model=think_model,
        speak_model=voice,
        greeting=settings.get("deepgram_agent_greeting", "") or None,
    )
    return DeepgramAgentProvider(config), voice, think_model


def _build_elevenlabs_realtime(settings: dict) -> tuple[Any, str, str]:
    """ElevenLabs ConvAI drives a pre-configured agent — no model/voice here."""
    api_key = settings.get("elevenlabs_api_key", "")
    if not api_key:
        raise ValueError("ElevenLabs API key is required. Open Settings to enter it.")
    agent_id = settings.get("elevenlabs_agent_id", "")
    if not agent_id:
        raise ValueError(
            "ElevenLabs Agent ID is required (create an agent on the ElevenLabs "
            "dashboard). Open Settings to enter it."
        )

    from roomkit.providers.elevenlabs.config import ElevenLabsRealtimeConfig
    from roomkit.providers.elevenlabs.realtime import ElevenLabsRealtimeProvider

    config = ElevenLabsRealtimeConfig(api_key=api_key, agent_id=agent_id)
    return ElevenLabsRealtimeProvider(config), "", agent_id


def _build_xai_realtime(settings: dict) -> tuple[Any, str, str]:
    api_key = settings.get("xai_api_key", "")
    if not api_key:
        raise ValueError("xAI API key is required. Open Settings to enter it.")
    model = settings.get("xai_model", "") or "grok-2-audio"
    voice = settings.get("xai_voice", "") or "eve"

    from roomkit.providers.xai.realtime import XAIRealtimeProvider

    return XAIRealtimeProvider(api_key=api_key, model=model), voice, model


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
                _apply_server_vad(provider_config, settings, "openai")
            if not settings.get("openai_interrupt_response", True):
                provider_config["interrupt_response"] = False
            if not settings.get("openai_create_response", True):
                provider_config["create_response"] = False
        else:
            # "none" — disable turn detection entirely
            provider_config["turn_detection_type"] = None
        # Independent of turn detection; omitted unless set so non-reasoning
        # models (gpt-4o-realtime) keep working untouched.
        effort = settings.get("openai_reasoning_effort", "")
        if effort:
            provider_config["reasoning_effort"] = effort
    elif provider_name == "xai":
        # Wire-compatible with OpenAI's server VAD; xAI honours the same
        # three tuning keys (no semantic VAD, no disabling).
        _apply_server_vad(provider_config, settings, "xai")
    return provider_config


def _apply_openai_semantic_vad(provider_config: dict[str, Any], settings: dict) -> None:
    eagerness = settings.get("openai_eagerness", "")
    if eagerness:
        try:
            provider_config["eagerness"] = float(eagerness)
        except (ValueError, TypeError):
            pass


def _apply_server_vad(provider_config: dict[str, Any], settings: dict, prefix: str) -> None:
    """Copy the ``{prefix}_*`` server-VAD tuning settings into provider_config."""
    threshold = settings.get(f"{prefix}_vad_threshold", "")
    if threshold:
        try:
            provider_config["threshold"] = float(threshold)
        except (ValueError, TypeError):
            pass
    silence_ms = settings.get(f"{prefix}_silence_duration_ms", "")
    if silence_ms:
        try:
            provider_config["silence_duration_ms"] = int(silence_ms)
        except (ValueError, TypeError):
            pass
    prefix_ms = settings.get(f"{prefix}_prefix_padding_ms", "")
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
    denoiser: Any = None,
    debug_taps: Any,
    recorder: Any,
    recording_config: Any,
    sample_rate: int,
) -> Any:
    """Assemble the realtime ``AudioPipelineConfig`` (or ``None`` if nothing to do).

    Diarization + VAD get wired together with a transport→16 kHz contract
    because the VAD / diarization models are 16 kHz-only while most realtime
    providers stream at 24 kHz (ElevenLabs already runs at 16 kHz — the
    contract is then a no-op).  Other stages (AEC, debug taps, recorder)
    attach at the transport's native sample rate.  No denoiser in realtime —
    see ``_start_realtime``.
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
            denoiser=denoiser,
            vad=vad,
            diarization=diarization,
            contract=contract,
            debug_taps=debug_taps,
            recorder=recorder,
            recording_config=recording_config,
            inbound_dsp_threads=DSP_THREADS,
        )

    if aec is not None or denoiser is not None or debug_taps is not None or recorder is not None:
        return AudioPipelineConfig(
            aec=aec,
            denoiser=denoiser,
            debug_taps=debug_taps,
            recorder=recorder,
            recording_config=recording_config,
            inbound_dsp_threads=DSP_THREADS,
        )
    return None

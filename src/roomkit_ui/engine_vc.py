"""Voice-Channel (STT → LLM → TTS) session mixin for ``Engine``.

Owns the classical voice pipeline: a ``VoiceChannel`` wired to a
``LocalAudioBackend``, plus an ``AIChannel`` for the LLM turn.  Covers
local / Gradium / Deepgram STT, cloud-or-local AI providers, cached
TTS, VAD + diarization + smart-turn, skills, and MCP tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from roomkit_ui.agent_hooks import register_agent_hooks
from roomkit_ui.engine_audio import (
    DSP_THREADS,
    VC_INPUT_SAMPLE_RATE,
    build_audio_processing,
    build_debug_taps,
    build_recorder,
    notify_missing_aec,
    setup_diarization,
    usable_capture_source,
)
from roomkit_ui.engine_state import EngineState
from roomkit_ui.engine_vc_helpers import (
    announce_llm_model,
    build_azure_mai_stt,
    build_deepgram_stt,
    build_gradium_stt,
    build_interruption,
    build_tts_filter,
    build_turn_detector,
    build_turn_vad,
    log_vc_audio_pipeline,
    mcp_servers_configured,
    register_local_tool_hint,
    smart_turn_config,
    start_local_llm,
    stt_needs_turn_vad,
    turn_incomplete_wait_ms,
)
from roomkit_ui.features import STT_PROVIDER_FEATURES, require, unavailable_reason
from roomkit_ui.hooks import register_vc_hooks
from roomkit_ui.providers import create_ai_provider
from roomkit_ui.toolset import ToolSet
from roomkit_ui.tts import create_tts_provider, is_cached_tts, tts_cache_fields
from roomkit_ui.vc_agent import build_vc_agent

logger = logging.getLogger(__name__)

_BLOCK_MS = 20


class VoiceChannelMixin:
    """STT → LLM → TTS session setup for ``Engine``.

    Attribute annotations mirror the concrete ``Engine`` so mypy can type
    ``self._attitude`` and friends from inside mixin methods.
    """

    _state: EngineState
    _attitude: str
    _attitude_name: str
    _base_system_prompt: str
    _stt: Any
    _tts: Any
    _backend: Any
    _channel: Any
    _ai_channel: Any
    _kit: Any
    _session: Any
    _mcp: Any
    _diarization: Any
    _primary_speaker_mode: bool
    _primary_speaker_name: str
    _ai_pricing: Any
    _usage_cost: float
    _usage_in: int
    _usage_out: int
    _pending_tool_calls: int
    _capture_source: Any
    _capture_since: Any
    _vc_agent: Any

    def _accumulate_usage(self, usage: dict) -> None:
        """Add one AI response's token usage to the session totals and emit.

        Called from the ON_AI_RESPONSE hook.  Cost is priced with the active
        model's catalog ``ModelPricing`` when roomkit carries one; without it
        (local models, unknown ids) only token counts are reported.
        """
        self._usage_in += (
            _usage_int(usage, "input_tokens")
            + _usage_int(usage, "cache_read_input_tokens")
            + _usage_int(usage, "cache_creation_input_tokens")
        )
        self._usage_out += _usage_int(usage, "output_tokens")
        if self._ai_pricing is not None:
            try:
                self._usage_cost += self._ai_pricing.cost_for(usage)
            except Exception:
                logger.debug("cost_for() failed for usage=%s", usage, exc_info=True)
        payload = {
            "cost_usd": self._usage_cost if self._ai_pricing is not None else None,
            "input_tokens": self._usage_in,
            "output_tokens": self._usage_out,
        }
        try:
            self.session_cost.emit(payload)  # type: ignore[attr-defined]
        except Exception:
            pass

    async def _start_voice_channel(self, settings: dict) -> None:
        try:
            system_prompt = self._compose_session_prompt(settings)  # type: ignore[attr-defined]
            inference_device = settings.get("inference_device", "cpu")
            aec_mode = settings.get("aec_mode", "webrtc")
            denoise_mode = settings.get("denoise", "none")

            # 1-2. STT + TTS providers
            stt, stt_provider_name = await self._build_stt(settings, inference_device)
            self._stt = stt
            tts, output_sample_rate = await self._build_tts(settings, inference_device)
            self._tts = tts  # type: ignore[attr-defined]

            # 3. LLM provider
            self.loading_status.emit("Connecting to LLM…")  # type: ignore[attr-defined]
            llm_provider_name = settings.get("vc_llm_provider", "anthropic")
            ai_provider = create_ai_provider(llm_provider_name, settings)
            model = ai_provider.model_name
            self._ai_pricing = _model_pricing(ai_provider)  # type: ignore[attr-defined]
            announce_llm_model(ai_provider, self.session_notice.emit)  # type: ignore[attr-defined]
            await start_local_llm(ai_provider, self.loading_status.emit)  # type: ignore[attr-defined]

            # 4-5. Audio backend
            input_sample_rate = VC_INPUT_SAMPLE_RATE
            frame_size = input_sample_rate * _BLOCK_MS // 1000
            aec, denoiser = build_audio_processing(
                aec_mode, denoise_mode, input_sample_rate, frame_size
            )
            notify_missing_aec(aec_mode, aec, self.session_notice.emit)  # type: ignore[attr-defined]
            backend = self._build_vc_backend(settings, aec, output_sample_rate)
            self._backend = backend  # type: ignore[attr-defined]
            log_vc_audio_pipeline(aec, denoiser, input_sample_rate, output_sample_rate)

            # 6. VAD, diarization, interruption, turn detector → the pipeline
            pipeline = await self._build_vc_pipeline(
                settings, stt, stt_provider_name, inference_device, aec, denoiser
            )

            # 7. VoiceChannel
            tts_filter = build_tts_filter(settings)
            voice = _build_voice_channel(stt, tts, backend, pipeline, tts_filter)
            self._channel = voice  # type: ignore[attr-defined]

            # 8-9. Skills, tools, then the AIChannel that takes their options
            ai_channel, tools, skills_registry = await self._build_vc_ai_channel(
                settings, ai_provider, llm_provider_name, system_prompt
            )
            self._ai_channel = ai_channel  # type: ignore[attr-defined]

            # 10-11. Framework + hooks
            voice_binding = await self._open_vc_room(
                settings, voice, ai_channel, tts_filter, llm_provider_name
            )

            # 12. Connect and start
            self.loading_status.emit("Starting voice channel…")  # type: ignore[attr-defined]
            await self._listen(backend, voice, voice_binding)

            self._spk_rms_queue.clear()  # type: ignore[attr-defined]
            self._spk_timer.start()  # type: ignore[attr-defined]
            self._pending_tool_calls = 0  # type: ignore[attr-defined]
            self._watchdog.start()  # type: ignore[attr-defined]

            self._enter_active()  # type: ignore[attr-defined]

            self._emit_session_info(  # type: ignore[attr-defined]
                provider=llm_provider_name,
                model=model,
                tools=tools,
                skills_registry=skills_registry,
                agent=self._vc_agent.summary,
            )

        except Exception as e:
            logger.exception("Failed to start voice channel session")
            await self._fail_start(str(e))  # type: ignore[attr-defined]

    async def _build_vc_pipeline(
        self,
        settings: dict,
        stt: Any,
        stt_provider_name: str,
        inference_device: str,
        aec: Any,
        denoiser: Any,
    ) -> Any:
        """The session's AudioPipelineConfig: VAD (local or turnless STT),
        diarization, barge-in, turn detector, debug taps and recording."""
        from roomkit.voice.pipeline.config import AudioPipelineConfig

        vad = self._build_vc_vad(settings, stt_provider_name, inference_device)
        diarization = setup_diarization(
            self,
            settings,
            vad_available=vad is not None,
            inference_device=inference_device,
        )
        interruption = build_interruption(
            settings, stt_streams=bool(getattr(stt, "supports_streaming", False))
        )
        turn_detector = await self._build_turn_detector(settings, inference_device)
        recorder, recording_config = build_recorder(settings)
        return AudioPipelineConfig(
            aec=aec,
            denoiser=denoiser,
            vad=vad,
            interruption=interruption,
            diarization=diarization,
            turn_detector=turn_detector,
            turn_incomplete_wait_ms=turn_incomplete_wait_ms(settings),
            debug_taps=build_debug_taps(settings),
            recorder=recorder,
            recording_config=recording_config,
            inbound_dsp_threads=DSP_THREADS,
        )

    async def _build_vc_ai_channel(
        self, settings: dict, ai_provider: Any, llm_provider_name: str, system_prompt: str
    ) -> tuple[Any, list[dict], Any]:
        """The AIChannel, after the skills, tools and agent parts it is built with.

        Returns ``(ai_channel, tools, skills_registry)``.
        """
        from roomkit.channels.ai import AIChannel
        from roomkit.models import RetryPolicy

        toolset, skills_registry = await self._load_vc_tools(settings, llm_provider_name)
        self._vc_agent = build_vc_agent(
            settings,
            ai_provider,
            self.session_notice.emit,  # type: ignore[attr-defined]
            tools=bool(toolset.all),
        )

        ai_channel = AIChannel(
            "ai",
            provider=ai_provider,
            system_prompt=system_prompt,
            tool_handler=self._handle_tool_call,  # type: ignore[attr-defined]
            config_provider=toolset.turn_config(),
            skills=skills_registry,
            # Provider SDKs no longer retry (Anthropic stopped in roomkit
            # 0.96); a 429/529 would fail the turn into silence.  Retries
            # only run while nothing has been streamed, so none is heard.
            retry_policy=RetryPolicy(max_retries=2, base_delay_seconds=0.5, max_delay_seconds=4.0),
            **toolset.channel_options(),
            **self._vc_agent.channel_options(),
        )
        return ai_channel, toolset.all, skills_registry

    async def _load_vc_tools(self, settings: dict, llm_provider_name: str) -> tuple[ToolSet, Any]:
        """The session's tools and skills: none for a local model with
        "supports tool use" off.  Returns ``(toolset, skills_registry)``."""
        if llm_provider_name == "local" and not settings.get("vc_local_tools", True):
            logger.info("Local model tool support disabled — skipping MCP/tools")
            return ToolSet(builtin=[], cli=[], mcp=[]), None
        skills_registry = self._load_skills(settings)
        if mcp_servers_configured(settings):
            self.loading_status.emit("Connecting MCP servers…")  # type: ignore[attr-defined]
        toolset = await self._setup_tools(settings)  # type: ignore[attr-defined]
        return toolset, skills_registry

    async def _open_vc_room(
        self,
        settings: dict,
        voice: Any,
        ai_channel: Any,
        tts_filter: Any,
        llm_provider_name: str,
    ) -> Any:
        """Build the kit, attach both channels to the durable room, register
        the hooks.  Returns the voice channel's binding."""
        from roomkit import RoomKit
        from roomkit.models.enums import ChannelCategory

        from roomkit_ui.memory import ROOM_ID, ensure_room

        kit, _store = self._build_kit(RoomKit, settings)  # type: ignore[attr-defined]
        self._kit = kit  # type: ignore[attr-defined]
        kit.register_channel(voice)
        kit.register_channel(ai_channel)
        if self._vc_agent.background:
            # The agent itself does the work, in a room of its own, with the
            # session's tools (ToolSet.turn_config); its result comes back as
            # a turn it speaks.
            kit.setup_background(ai_channel)
        await ensure_room(kit)

        voice_binding = await kit.attach_channel(ROOM_ID, "voice")
        # No tools in the binding's metadata: they come with each turn
        # (ToolSet.turn_config), in this room and in a background task's.
        await kit.attach_channel(ROOM_ID, "ai", category=ChannelCategory.INTELLIGENCE)
        register_vc_hooks(kit, self, tts_filter=tts_filter)
        register_agent_hooks(kit, self)
        if llm_provider_name == "local":
            register_local_tool_hint(kit, self.error_occurred.emit)  # type: ignore[attr-defined]
        return voice_binding

    def _build_vc_backend(self, settings: dict, aec: Any, output_sample_rate: int) -> Any:
        """The session's LocalAudioBackend, on the shared microphone when it fits.

        Subscribed to the shared source, the session can replay what was
        said before it existed — the request that followed the wake word.
        """
        from roomkit.voice.backends.local import LocalAudioBackend

        return LocalAudioBackend(
            input_sample_rate=VC_INPUT_SAMPLE_RATE,
            output_sample_rate=output_sample_rate,
            block_duration_ms=_BLOCK_MS,
            input_device=settings.get("input_device"),
            output_device=settings.get("output_device"),
            aec=aec,
            mute_mic_during_playback=aec is None,
            source=usable_capture_source(self._capture_source, VC_INPUT_SAMPLE_RATE),
        )

    async def _listen(self, backend: Any, voice: Any, voice_binding: Any) -> None:
        """Open this session on the backend and start capturing the mic.

        With a wake word's replay mark, the backend replays the shared
        source from there, so the words spoken while the session was being
        built reach the STT.  The user's mute is applied before capture
        starts — replay included — so one pressed while the session was
        connecting holds from the first frame.
        """
        from roomkit_ui.memory import ROOM_ID

        mark = self._capture_since
        metadata = {"capture_since": mark} if mark is not None else None
        session = await backend.connect(ROOM_ID, "local-user", "voice", metadata=metadata)
        self._session = session
        self._apply_mic_mute(session)  # type: ignore[attr-defined]
        voice.bind_session(session, ROOM_ID, voice_binding)
        await backend.start_listening(session)

    # -- STT ---------------------------------------------------------------

    async def _build_stt(self, settings: dict, inference_device: str) -> tuple[Any, str]:
        """Build the STT provider. Returns (stt, provider_name)."""
        stt_provider_name = settings.get("vc_stt_provider", "local")
        stt_language = settings.get("stt_language", "") or "en"
        feature = STT_PROVIDER_FEATURES.get(stt_provider_name)
        if feature is not None:
            require(feature)

        if stt_provider_name == "gradium":
            stt = build_gradium_stt(settings, stt_language, self.loading_status.emit)  # type: ignore[attr-defined]
        elif stt_provider_name == "deepgram":
            stt = build_deepgram_stt(settings, stt_language, self.loading_status.emit)  # type: ignore[attr-defined]
        elif stt_provider_name == "azure_mai":
            stt = build_azure_mai_stt(settings, self.loading_status.emit)  # type: ignore[attr-defined]
        else:
            stt = await self._build_local_stt(settings, stt_language, inference_device)

        # Remote providers (gradium, deepgram) may also have warmup
        if stt_provider_name != "local" and hasattr(stt, "warmup"):
            self.loading_status.emit("Warming up STT…")  # type: ignore[attr-defined]
            await stt.warmup()
        return stt, stt_provider_name

    async def _build_local_stt(
        self, settings: dict, stt_language: str, inference_device: str
    ) -> Any:
        from roomkit.voice.stt.sherpa_onnx import SherpaOnnxSTTProvider

        from roomkit_ui.model_manager import build_stt_config

        stt_model_id = settings.get("vc_stt_model", "")
        if not stt_model_id:
            raise ValueError(
                "No STT model selected. Download one in AI Models and select it in Settings."
            )
        stt_translate = settings.get("stt_translate", False)
        stt_key = ("stt", stt_model_id, stt_language, stt_translate, inference_device)
        cached_stt = self._get_cached("stt", stt_key)  # type: ignore[attr-defined]
        if cached_stt is not None:
            logger.info("STT: reusing cached %s", stt_model_id)
            return cached_stt

        self.loading_status.emit("Loading STT model…")  # type: ignore[attr-defined]
        local_stt_config = build_stt_config(
            stt_model_id,
            language=stt_language,
            translate=stt_translate,
            provider=inference_device,
        )
        stt = SherpaOnnxSTTProvider(local_stt_config)
        logger.info("STT: model=%s, language=%s", stt_model_id, stt_language)
        if hasattr(stt, "warmup"):
            self.loading_status.emit("Warming up STT model…")  # type: ignore[attr-defined]
            await stt.warmup()
        self._set_cached("stt", stt_key, stt)  # type: ignore[attr-defined]
        return stt

    # -- TTS ---------------------------------------------------------------

    async def _build_tts(self, settings: dict, inference_device: str) -> tuple[Any, int]:
        """Build the TTS provider. Returns (tts, output_sample_rate)."""
        tts_provider_name = settings.get("vc_tts_provider", "piper")
        tts_model_id = settings.get("vc_tts_model", "")
        tts_key = _tts_cache_key(settings, tts_provider_name, tts_model_id, inference_device)
        cached_tts = self._get_cached("tts", tts_key)  # type: ignore[attr-defined]
        if cached_tts is not None:
            tts, output_sample_rate = cached_tts
            logger.info("TTS: reusing cached %s/%s", tts_provider_name, tts_model_id)
        else:
            self.loading_status.emit("Loading TTS model…")  # type: ignore[attr-defined]
            tts, output_sample_rate = create_tts_provider(tts_provider_name, settings)
            if hasattr(tts, "warmup"):
                self.loading_status.emit("Warming up TTS model…")  # type: ignore[attr-defined]
                await tts.warmup()
            # Cache local TTS providers (ONNX models are expensive to load)
            if is_cached_tts(tts_provider_name):
                self._set_cached("tts", tts_key, (tts, output_sample_rate))  # type: ignore[attr-defined]
        logger.info("TTS: provider=%s, sample_rate=%d", tts_provider_name, output_sample_rate)
        return tts, output_sample_rate

    # -- VAD + diarization ------------------------------------------------

    @staticmethod
    def _build_vc_vad(settings: dict, stt_provider_name: str, inference_device: str) -> Any:
        """Build a VAD provider: for local STT, or for a cloud STT that finds no turns."""
        if stt_needs_turn_vad(stt_provider_name):
            return build_turn_vad(settings, inference_device)
        vad_model_id = settings.get("vc_vad_model", "") if stt_provider_name == "local" else ""
        if not vad_model_id:
            return None

        from roomkit_ui.model_manager import build_vad_config, is_vad_model_downloaded

        if not is_vad_model_downloaded(vad_model_id):
            logger.warning("VAD model %s not downloaded — no VAD", vad_model_id)
            return None

        from roomkit.voice.pipeline.vad.sherpa_onnx import SherpaOnnxVADProvider

        vad_config = build_vad_config(vad_model_id, provider=inference_device, settings=settings)
        logger.info("VAD: %s", vad_model_id)
        return SherpaOnnxVADProvider(vad_config)

    # -- Turn detector ----------------------------------------------------

    async def _build_turn_detector(self, settings: dict, inference_device: str) -> Any:
        """The Smart Turn detector, cached across sessions and loaded before the first turn.

        Loading it imports ``transformers`` (seconds) and the ONNX model; done
        here, off the loop, the first turn no longer waits for it.  Without the
        packages the session runs without it and says so: the detector would
        fail every turn and, after three, never let a turn end.
        """
        config = smart_turn_config(settings, inference_device)
        if config is None:
            return None
        reason = unavailable_reason("smart-turn")
        if reason is not None:
            self.session_notice.emit(f"Turn detection is off for this session. {reason}")  # type: ignore[attr-defined]
            return None
        key = ("turn", config.model_path, config.threshold, config.provider)
        detector = self._get_cached("turn", key)  # type: ignore[attr-defined]
        if detector is not None:
            return detector
        detector = build_turn_detector(config)
        self.loading_status.emit("Loading turn detector…")  # type: ignore[attr-defined]
        try:
            await asyncio.to_thread(detector.warmup)
        except Exception as exc:
            logger.exception("Smart Turn failed to load")
            self.session_notice.emit(f"Turn detection is off for this session: {exc}")  # type: ignore[attr-defined]
            return None
        self._set_cached("turn", key, detector)  # type: ignore[attr-defined]
        return detector

    # -- Skills + session info -------------------------------------------

    def _load_skills(self, settings: dict) -> Any:
        try:
            from roomkit_ui.skill_manager import build_registry

            sources = json.loads(settings.get("skill_sources", "[]"))
            enabled = json.loads(settings.get("enabled_skills", "[]"))
            if not sources or not enabled:
                return None
            self.loading_status.emit("Loading skills…")  # type: ignore[attr-defined]
            registry = build_registry(sources, enabled)
            if registry.skill_count == 0:
                return None
            logger.info("Skills loaded: %s", ", ".join(registry.skill_names))
            return registry
        except Exception:
            logger.exception("Failed to load skills")
            return None


def _build_voice_channel(stt: Any, tts: Any, backend: Any, pipeline: Any, tts_filter: Any) -> Any:
    """The session's VoiceChannel.

    close_providers=False: the engine owns the STT/TTS lifecycle (it reuses
    cached models across sessions and closes TTS itself to avoid a
    double-aclose hang), so close() must not close them.  The backend is
    still closed by close().

    pipeline_speakers with diarization: each transcription carries the voice
    heard the longest over its own utterance (``speaker`` / ``sender_name``).
    roomkit refuses it without a diarization stage, which needs the VAD.
    """
    from roomkit import VoiceChannel

    return VoiceChannel(
        "voice",
        stt=stt,
        tts=tts,
        backend=backend,
        pipeline=pipeline,
        tts_filter=tts_filter,
        close_providers=False,
        pipeline_speakers=pipeline.diarization is not None,
    )


# ---------------------------------------------------------------------------
# TTS cache key (module-level — no engine state)
# ---------------------------------------------------------------------------

# Built from a reference recording of the voice to clone (tts/qwen3.py,
# tts/neutts.py) rather than from a model id alone.
_VOICE_CLONING_TTS = frozenset({"qwen3", "neutts"})


def _tts_cache_key(settings: dict, provider: str, model: str, device: str) -> tuple:
    """Everything a cached TTS was built from, so a change rebuilds it.

    A voice-cloning TTS speaks with the reference it was built from: its key
    carries the reference file — path and modification time, so a recording
    replaced in place counts — and its transcript.
    """
    key: tuple = ("tts", provider, model, device, *tts_cache_fields(provider, settings))
    if provider not in _VOICE_CLONING_TTS:
        return key
    ref_audio = settings.get("vc_tts_ref_audio", "")
    try:
        ref_mtime: int | None = os.stat(ref_audio).st_mtime_ns if ref_audio else None
    except OSError:
        ref_mtime = None
    return (*key, ref_audio, ref_mtime, settings.get("vc_tts_ref_text", ""))


# ---------------------------------------------------------------------------
# Usage accounting helpers (module-level — no engine state)
# ---------------------------------------------------------------------------


def _usage_int(usage: dict, key: str) -> int:
    """A usage counter as int, treating absent/None/garbage as zero."""
    try:
        return int(usage.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _model_pricing(provider: Any) -> Any:
    """The active model's catalog ``ModelPricing``, or None when unknown.

    ``catalog_entry()`` returns None for ids the offline catalog does not
    carry (local/custom models); vLLM providers ship an empty catalog on
    purpose.  Never raises — pricing is decoration, not session-critical.
    """
    try:
        entry = provider.catalog_entry()
    except Exception:
        return None
    return getattr(entry, "pricing", None) if entry is not None else None

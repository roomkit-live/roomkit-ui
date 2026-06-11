"""Voice-Channel (STT → LLM → TTS) session mixin for ``Engine``.

Owns the classical voice pipeline: a ``VoiceChannel`` wired to a
``LocalAudioBackend``, plus an ``AIChannel`` for the LLM turn.  Covers
local / Gradium / Deepgram STT, cloud-or-local AI providers, cached
TTS, VAD + diarization + smart-turn, skills, and MCP tools.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from roomkit_ui.engine_audio import (
    build_audio_processing,
    build_debug_taps,
    build_recorder,
    build_telemetry,
    resolve_attitude,
    setup_diarization,
)
from roomkit_ui.engine_state import EngineState
from roomkit_ui.hooks import register_vc_hooks
from roomkit_ui.providers import create_ai_provider
from roomkit_ui.tts import create_tts_provider

logger = logging.getLogger(__name__)


class VoiceChannelMixin:
    """STT → LLM → TTS session setup for ``Engine``.

    Attribute annotations mirror the concrete ``Engine`` so mypy can type
    ``self._attitude`` and friends from inside mixin methods.
    """

    _state: EngineState
    _attitude: str
    _attitude_name: str
    _base_system_prompt: str
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
    _pending_tool_calls: int

    async def _start_voice_channel(self, settings: dict) -> None:
        self._set_state(EngineState.CONNECTING)  # type: ignore[attr-defined]

        try:
            from roomkit import RoomKit, VoiceChannel
            from roomkit.channels.ai import AIChannel
            from roomkit.voice.backends.local import LocalAudioBackend
            from roomkit.voice.pipeline.config import AudioPipelineConfig

            base_prompt = settings.get(
                "system_prompt",
                "You are a friendly voice assistant. Be concise and helpful.",
            )
            # Cache the user's base prompt (without attitude) so the
            # set_attitude tool can rebuild the full prompt and update
            # AIChannel._system_prompt without reaching in to strip it.
            self._base_system_prompt = base_prompt
            system_prompt = base_prompt
            attitude = self._attitude or resolve_attitude(settings)
            if attitude:
                system_prompt = f"{system_prompt}\n\n# Attitude\n{attitude}"
                self._attitude = attitude
                if not self._attitude_name:
                    self._attitude_name = settings.get("selected_attitude", "") or attitude
            inference_device = settings.get("inference_device", "cpu")
            aec_mode = settings.get("aec_mode", "webrtc")
            denoise_mode = settings.get("denoise", "none")

            # 1-2. STT + TTS providers
            stt, stt_provider_name = await self._build_stt(settings, inference_device)
            tts, output_sample_rate = await self._build_tts(settings, inference_device)
            self._tts = tts  # type: ignore[attr-defined]

            # 3. LLM provider
            self.loading_status.emit("Connecting to LLM…")  # type: ignore[attr-defined]
            llm_provider_name = settings.get("vc_llm_provider", "anthropic")
            ai_provider = create_ai_provider(llm_provider_name, settings)
            model = ai_provider.model_name
            if llm_provider_name == "local":
                _wrap_local_provider_tool_errors(ai_provider, self.error_occurred.emit)  # type: ignore[attr-defined]

            # 4-5. Audio backend
            input_sample_rate = 16000
            block_ms = 20
            frame_size = input_sample_rate * block_ms // 1000
            aec, denoiser = build_audio_processing(
                aec_mode, denoise_mode, input_sample_rate, frame_size
            )
            backend = LocalAudioBackend(
                input_sample_rate=input_sample_rate,
                output_sample_rate=output_sample_rate,
                block_duration_ms=block_ms,
                input_device=settings.get("input_device"),
                output_device=settings.get("output_device"),
                aec=aec,
                mute_mic_during_playback=aec is None,
            )
            self._backend = backend  # type: ignore[attr-defined]
            _log_vc_audio_pipeline(aec, denoiser, input_sample_rate, output_sample_rate)

            # 6. VAD (local STT only), diarization, interruption, turn detector
            vad = self._build_vc_vad(settings, stt_provider_name, inference_device)
            diarization = setup_diarization(
                self,
                settings,
                vad_available=vad is not None,
                inference_device=inference_device,
            )
            interruption = _build_interruption(settings)
            turn_detector = _build_turn_detector(settings, inference_device)

            # 6.5. AudioPipelineConfig
            debug_taps = build_debug_taps(settings)
            recorder, recording_config = build_recorder(settings)
            pipeline = AudioPipelineConfig(
                aec=aec,
                denoiser=denoiser,
                vad=vad,
                interruption=interruption,
                diarization=diarization,
                turn_detector=turn_detector,
                debug_taps=debug_taps,
                recorder=recorder,
                recording_config=recording_config,
            )

            # 7. VoiceChannel
            voice = VoiceChannel("voice", stt=stt, tts=tts, backend=backend, pipeline=pipeline)
            self._channel = voice  # type: ignore[attr-defined]

            # 7.5. Skills + 8. AIChannel
            skip_tools = llm_provider_name == "local" and not settings.get("vc_local_tools", True)
            skills_registry = self._load_skills(settings) if not skip_tools else None

            ai_channel = AIChannel(
                "ai",
                provider=ai_provider,
                system_prompt=system_prompt,
                tool_handler=self._handle_tool_call,  # type: ignore[attr-defined]
                skills=skills_registry,
            )
            self._ai_channel = ai_channel  # type: ignore[attr-defined]

            # 9. MCP tools
            tools: list[dict] = []
            if skip_tools:
                logger.info("Local model tool support disabled — skipping MCP/tools")
            else:
                if _mcp_servers_configured(settings):
                    self.loading_status.emit("Connecting MCP servers…")  # type: ignore[attr-defined]
                tools, _has_mcp = await self._setup_mcp_tools(settings)  # type: ignore[attr-defined]

            # 10-11. Framework + hooks
            telemetry = build_telemetry(settings)
            kit = RoomKit(telemetry=telemetry)
            self._kit = kit  # type: ignore[attr-defined]
            kit.register_channel(voice)
            kit.register_channel(ai_channel)
            await kit.create_room(room_id="local-demo")

            from roomkit.models.enums import ChannelCategory

            voice_binding = await kit.attach_channel("local-demo", "voice")
            await kit.attach_channel(
                "local-demo",
                "ai",
                category=ChannelCategory.INTELLIGENCE,
                metadata={"tools": tools},
            )
            register_vc_hooks(kit, self)

            # 12. Connect and start
            self.loading_status.emit("Starting voice channel…")  # type: ignore[attr-defined]
            session = await backend.connect("local-demo", "local-user", "voice")
            self._session = session  # type: ignore[attr-defined]
            voice.bind_session(session, "local-demo", voice_binding)
            await backend.start_listening(session)

            self._spk_rms_queue.clear()  # type: ignore[attr-defined]
            self._spk_timer.start()  # type: ignore[attr-defined]
            self._pending_tool_calls = 0  # type: ignore[attr-defined]
            self._watchdog.start()  # type: ignore[attr-defined]

            self._set_state(EngineState.ACTIVE)  # type: ignore[attr-defined]

            # Emit session info
            self._emit_vc_session_info(
                tools=tools,
                skills_registry=skills_registry,
                llm_provider_name=llm_provider_name,
                model=model,
            )

        except Exception as e:
            logger.exception("Failed to start voice channel session")
            self._set_state(EngineState.ERROR)  # type: ignore[attr-defined]
            self.error_occurred.emit(str(e))  # type: ignore[attr-defined]
            await self._cleanup()  # type: ignore[attr-defined]

    # -- STT ---------------------------------------------------------------

    async def _build_stt(self, settings: dict, inference_device: str) -> tuple[Any, str]:
        """Build the STT provider. Returns (stt, provider_name)."""
        stt_provider_name = settings.get("vc_stt_provider", "local")
        stt_language = settings.get("stt_language", "") or "en"

        if stt_provider_name == "gradium":
            stt = _build_gradium_stt(settings, stt_language, self.loading_status.emit)  # type: ignore[attr-defined]
        elif stt_provider_name == "deepgram":
            stt = _build_deepgram_stt(settings, stt_language, self.loading_status.emit)  # type: ignore[attr-defined]
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
        tts_key = ("tts", tts_provider_name, tts_model_id, inference_device)
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
            if tts_provider_name in ("piper", "qwen3", "neutts"):
                self._set_cached("tts", tts_key, (tts, output_sample_rate))  # type: ignore[attr-defined]
        logger.info("TTS: provider=%s, sample_rate=%d", tts_provider_name, output_sample_rate)
        return tts, output_sample_rate

    # -- VAD + diarization ------------------------------------------------

    @staticmethod
    def _build_vc_vad(settings: dict, stt_provider_name: str, inference_device: str) -> Any:
        """Build a VAD provider. Only enabled when using local STT."""
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

    def _emit_vc_session_info(
        self,
        *,
        tools: list[dict],
        skills_registry: Any,
        llm_provider_name: str,
        model: str,
    ) -> None:
        tool_info = [
            {"name": t.get("name", ""), "description": t.get("description", "")} for t in tools
        ]
        skill_info: list[dict] = []
        if skills_registry and skills_registry.skill_count > 0:
            skill_info = [
                {"name": m.name, "description": m.description}
                for m in skills_registry.all_metadata()
            ]
        info: dict = {
            "provider": llm_provider_name,
            "model": model,
            "tools": tool_info,
            "skills": skill_info,
        }
        if self._mcp and self._mcp.failed_servers:  # type: ignore[attr-defined]
            info["failed_servers"] = list(self._mcp.failed_servers)  # type: ignore[attr-defined]
        self.session_info.emit(info)  # type: ignore[attr-defined]
        if self._attitude_name:  # type: ignore[attr-defined]
            self.attitude_changed.emit(self._attitude_name)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Module-level builders (no engine state)
# ---------------------------------------------------------------------------


def _build_gradium_stt(settings: dict, stt_language: str, emit_status) -> Any:
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
    _try_set_int(stt_kwargs, "delay_in_frames", settings.get("gradium_stt_delay", ""))
    _try_set_float(stt_kwargs, "vad_threshold", settings.get("gradium_vad_threshold", ""))
    _try_set_int(stt_kwargs, "vad_steps", settings.get("gradium_vad_steps", ""))

    json_config: dict[str, Any] = {}
    _try_set_float(json_config, "temperature", settings.get("gradium_stt_temperature", ""))
    if json_config:
        stt_kwargs["json_config"] = json_config

    stt_config = GradiumSTTConfig(
        api_key=api_key, region=region, language=stt_language, **stt_kwargs
    )
    logger.info("STT: gradium, region=%s, language=%s", region, stt_language)
    return GradiumSTTProvider(stt_config)


def _build_deepgram_stt(settings: dict, stt_language: str, emit_status) -> Any:
    from roomkit.voice.stt.deepgram import DeepgramConfig, DeepgramSTTProvider

    emit_status("Connecting Deepgram STT…")
    api_key = settings.get("deepgram_api_key", "")
    if not api_key:
        raise ValueError("Deepgram API key is required for Deepgram STT.")
    dg_model = settings.get("deepgram_model", "nova-3")
    dg_config = DeepgramConfig(api_key=api_key, model=dg_model, language=stt_language)
    logger.info("STT: deepgram, model=%s, language=%s", dg_model, stt_language)
    return DeepgramSTTProvider(dg_config)


def _wrap_local_provider_tool_errors(ai_provider: Any, emit_error) -> None:
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
                    pass
            raise

    ai_provider.generate = _generate_with_tool_hint  # type: ignore[method-assign]


def _build_interruption(settings: dict) -> Any:
    from roomkit.voice.interruption import InterruptionConfig, InterruptionStrategy

    enabled = settings.get("vc_interruption", False)
    strategy = InterruptionStrategy.IMMEDIATE if enabled else InterruptionStrategy.DISABLED
    logger.info("Interruption: %s", strategy.value)
    return InterruptionConfig(strategy=strategy)


def _build_turn_detector(settings: dict, inference_device: str) -> Any:
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


def _log_vc_audio_pipeline(
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


def _mcp_servers_configured(settings: dict) -> bool:
    try:
        return any(s.get("enabled", True) for s in json.loads(settings.get("mcp_servers", "[]")))
    except (json.JSONDecodeError, TypeError):
        return False


def _try_set_int(target: dict[str, Any], key: str, raw: str) -> None:
    if not raw:
        return
    try:
        target[key] = int(raw)
    except (ValueError, TypeError):
        pass


def _try_set_float(target: dict[str, Any], key: str, raw: str) -> None:
    if not raw:
        return
    try:
        target[key] = float(raw)
    except (ValueError, TypeError):
        pass

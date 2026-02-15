"""Async engine wrapping roomkit — emits Qt signals for the UI."""

from __future__ import annotations

import asyncio
import collections
import json
import logging
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from roomkit_ui.builtin_tools import BUILTIN_TOOLS, handle_builtin_tool
from roomkit_ui.cleanup import cleanup_stale_fds, post_cleanup_monitor
from roomkit_ui.hooks import register_realtime_hooks, register_vc_hooks
from roomkit_ui.mcp_manager import MCPManager
from roomkit_ui.providers import create_ai_provider
from roomkit_ui.tts import create_tts_provider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Voice error log handler — surfaces roomkit errors in the chat
# ---------------------------------------------------------------------------


class _VoiceErrorLogHandler(logging.Handler):
    """Intercept ERROR logs from roomkit.voice and emit on the engine signal.

    This lets the UI show STT/TTS connection errors (e.g. "insufficient
    credits") that roomkit catches internally and retries silently.
    Debounces repeated identical messages.
    """

    def __init__(self, engine: Engine) -> None:  # type: ignore[name-defined]
        super().__init__(level=logging.ERROR)
        self._engine_ref: Any = engine
        self._last_msg = ""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            engine = self._engine_ref
            if engine is None or engine._state != "active":
                return
            msg = record.getMessage()
            # Extract the root cause from the traceback if present
            if record.exc_info and record.exc_info[1]:
                cause = str(record.exc_info[1])
                # Use the exception message — more user-friendly
                msg = cause
            # Debounce identical messages
            if msg == self._last_msg:
                return
            self._last_msg = msg
            engine.error_occurred.emit(msg)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class Engine(QObject):
    """Manages a roomkit voice session and bridges events to Qt signals."""

    state_changed = Signal(str)  # idle / connecting / active / error
    transcription = Signal(str, str, bool, str)  # text, role, is_final, speaker_name
    speaker_identified = Signal(str, float)  # speaker_name, confidence
    mic_audio_level = Signal(float)  # 0.0-1.0
    speaker_audio_level = Signal(float)  # 0.0-1.0
    user_speaking = Signal(bool)
    ai_speaking = Signal(bool)
    error_occurred = Signal(str)
    tool_use = Signal(str, str)  # tool_name, arguments_json
    tool_use_app = Signal(str, str, str, str)  # name, args_json, resource_uri, server_name
    tool_result_app = Signal(str, str)  # name, result_json
    mcp_status = Signal(str)  # status message
    loading_status = Signal(str)  # loading progress message
    session_info = Signal(dict)  # {provider, model, tools, failed_servers}
    attitude_changed = Signal(str)  # attitude name (empty string = cleared)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._kit: Any = None
        self._channel: Any = None
        self._ai_channel: Any = None
        self._session: Any = None
        self._transport: Any = None
        self._backend: Any = None  # LocalAudioBackend for voice channel mode
        self._tts: Any = None
        self._mcp: MCPManager | None = None
        self._mic_muted = False
        self._state = "idle"
        self._attitude: str = ""  # full description text (injected into prompt)
        self._attitude_name: str = ""  # short display name for the header
        # Diarization state
        self._diarization: Any = None
        self._current_speaker_id: str = ""
        self._primary_speaker_mode: bool = False
        self._primary_speaker_name: str = ""
        # Realtime partial transcription accumulator: Gemini/OpenAI send
        # incremental fragments, but the UI expects full accumulated text.
        self._partial_buffers: dict[str, str] = {}  # role → accumulated text
        self._partial_speakers: dict[str, str] = {}  # role → best speaker ID this utterance
        # Model cache: persist heavy ONNX models across sessions to avoid
        # reloading STT / TTS / diarization on every conversation start.
        # Maps type → (cache_key_tuple, provider_instance).
        self._cached_models: dict[str, tuple[tuple, Any]] = {}
        self._cleanup_monitor_task: asyncio.Task | None = None

        # Log handler to surface roomkit voice errors in the UI
        self._log_handler = _VoiceErrorLogHandler(self)
        logging.getLogger("roomkit.voice").addHandler(self._log_handler)

        # Speaker RMS queue: audio arrives in bursts from the provider but
        # plays back at a steady 20 ms cadence.  We split incoming chunks
        # into block-sized RMS values and drain them with a timer that
        # matches the real playback rate.
        self._spk_rms_queue: collections.deque[float] = collections.deque()
        self._spk_timer = QTimer(self)
        self._spk_timer.setInterval(20)  # one playback block
        self._spk_timer.timeout.connect(self._drain_speaker_level)

    # -- model cache ---------------------------------------------------------

    def _get_cached(self, model_type: str, cache_key: tuple) -> Any | None:
        """Return a cached provider if the key matches, else None."""
        entry = self._cached_models.get(model_type)
        if entry is not None and entry[0] == cache_key:
            return entry[1]
        return None

    def _set_cached(self, model_type: str, cache_key: tuple, provider: Any) -> None:
        self._cached_models[model_type] = (cache_key, provider)

    def clear_model_cache(self) -> None:
        """Release all cached models (call on app quit)."""
        self._cached_models.clear()

    @property
    def state(self) -> str:
        return self._state

    def set_mic_muted(self, muted: bool) -> None:
        self._mic_muted = muted
        if self._transport is not None and self._session is not None:
            try:
                self._transport.set_input_muted(self._session, muted)
            except Exception:
                pass
        # Voice channel mode uses LocalAudioBackend (no set_input_muted)

    # -- register our own callbacks (roomkit uses append-based lists) --------

    def _register_callbacks(self, provider: Any, transport: Any) -> None:
        # NOTE: on_transcription is NOT registered here — the channel fires
        # ON_TRANSCRIPTION hooks which register_realtime_hooks() handles.
        # Registering both would cause double transcription in the UI.
        provider.on_speech_start(self._on_speech_start)
        provider.on_speech_end(self._on_speech_end)
        provider.on_response_start(self._on_response_start)
        provider.on_response_end(self._on_response_end)
        provider.on_error(self._on_provider_error)

    # -- callbacks -----------------------------------------------------------

    def _on_transcription(self, _s: Any, text: str, role: str, is_final: bool) -> None:
        """Realtime transcription callback.

        Gemini/OpenAI send incremental fragments for partials.
        Accumulate them so the signal always carries the full text.
        """
        try:
            speaker = self._current_speaker_id if role == "user" else ""

            # Primary speaker mode: block non-primary user transcriptions
            if (
                role == "user"
                and self._primary_speaker_mode
                and self._primary_speaker_name
                and speaker != self._primary_speaker_name
            ):
                if is_final:
                    self._partial_buffers.pop(role, None)
                    label = speaker if speaker and speaker != "unknown" else "Unknown"
                    self.transcription.emit(str(text), "other", True, label)
                return

            if is_final:
                self._partial_buffers.pop(role, None)
                self.transcription.emit(str(text), str(role), True, speaker)
            else:
                buf = self._partial_buffers.get(role, "")
                buf += text
                self._partial_buffers[role] = buf
                self.transcription.emit(buf, str(role), False, speaker)
        except Exception:
            pass

    def _drain_speaker_level(self) -> None:
        """Pop one RMS value per timer tick → matches real playback cadence."""
        if self._spk_rms_queue:
            self.speaker_audio_level.emit(self._spk_rms_queue.popleft())

    def _on_speech_start(self, _s: Any) -> None:
        try:
            self.user_speaking.emit(True)
        except Exception:
            pass

    def _on_speech_end(self, _s: Any) -> None:
        try:
            self.user_speaking.emit(False)
        except Exception:
            pass

    def _on_response_start(self, _s: Any) -> None:
        try:
            self.ai_speaking.emit(True)
        except Exception:
            pass

    def _on_response_end(self, _s: Any) -> None:
        try:
            self.ai_speaking.emit(False)
        except Exception:
            pass

    def _on_provider_error(self, _s: Any, code: str, message: str) -> None:
        # Suppress errors during shutdown — WebSocket close races are expected
        if self._state not in ("active", "connecting"):
            logger.debug("Suppressed provider error (%s): %s: %s", self._state, code, message)
            return
        try:
            friendly = self._friendly_error(code, message)
            logger.warning("Provider error: %s: %s → %s", code, message, friendly)
            self.error_occurred.emit(friendly)
        except Exception:
            pass

    def _on_transport_speaker_change(self, session: Any, result: Any) -> None:
        """Handle speaker change events directly from the transport pipeline."""
        speaker_id = result.speaker_id
        confidence = result.confidence
        self._current_speaker_id = speaker_id
        try:
            self.speaker_identified.emit(speaker_id, confidence)
        except Exception:
            pass

        # Primary speaker gating: gate audio when a *different* enrolled
        # speaker is positively identified.  Unknown / empty speakers get
        # benefit of the doubt (diarization hasn't decided yet).
        if self._primary_speaker_mode and self._primary_speaker_name:
            gate = (
                bool(speaker_id)
                and speaker_id != "unknown"
                and speaker_id != self._primary_speaker_name
            )
            if self._transport is not None:
                self._transport.set_input_gated(session, gate)

    @staticmethod
    def _friendly_error(code: str, message: str) -> str:
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

    # -- tool calls ----------------------------------------------------------

    async def _handle_tool_call(
        self,
        session: Any,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Handle built-in tools or forward to MCP manager."""
        # Check if this is an MCP App tool (has ui:// resource)
        app_info = self._mcp.get_app_tool_info(name) if self._mcp else None

        try:
            if app_info is not None:
                self.tool_use_app.emit(
                    name,
                    json.dumps(arguments),
                    app_info["uri"],
                    app_info["server"],
                )
            else:
                self.tool_use.emit(name, json.dumps(arguments))
        except Exception:
            pass

        # Handle paste_text — copy text to clipboard and simulate paste
        if name == "paste_text":
            return self._paste_text(arguments.get("text", ""))

        # Handle end_conversation — schedule stop after a delay so the
        # agent's goodbye response can be spoken before disconnecting.
        if name == "end_conversation":
            asyncio.get_event_loop().call_later(3.0, lambda: asyncio.ensure_future(self.stop()))
            return '{"status": "ok", "message": "Ending conversation in a few seconds."}'

        # Handle attitude changes (needs engine state, not pure builtin)
        if name == "set_attitude":
            return self._apply_attitude_by_name(arguments.get("name", ""))

        # Try built-in tools first
        builtin_result = handle_builtin_tool(name)
        if builtin_result is not None:
            return builtin_result

        if self._mcp is None:
            return '{"error": "Unknown tool"}'
        result = await self._mcp.handle_tool_call(session, name, arguments)
        # MCP/anyio can leak orphaned timer callbacks under qasync when a
        # tool call fails or the server crashes.  Run a lightweight cleanup
        # after every MCP call to prevent 100% CPU spin loops.
        # timers_only=True: don't touch FD notifiers during an active session.
        cleanup_stale_fds(timers_only=True)

        # Notify the UI so the app widget can display the result
        if app_info is not None:
            try:
                self.tool_result_app.emit(name, result)
            except Exception:
                pass

        return result

    def _apply_attitude_by_name(self, name: str) -> str:
        """Look up an attitude by name and apply it. Rejects unknown names."""
        if not name:
            return json.dumps({"error": "Attitude name is required."})

        # Look up in presets
        from roomkit_ui.widgets.settings.constants import ATTITUDE_PRESETS

        for pname, ptext in ATTITUDE_PRESETS:
            if pname.lower() == name.lower():
                return self._apply_attitude(pname, ptext)

        # Look up in custom attitudes
        try:
            from roomkit_ui.settings import load_settings

            settings = load_settings()
            for att in json.loads(settings.get("custom_attitudes", "[]")):
                if att.get("name", "").lower() == name.lower():
                    return self._apply_attitude(att["name"], att.get("text", ""))
        except (json.JSONDecodeError, TypeError):
            pass

        # Not found — return error with available names
        available = [n for n, _ in ATTITUDE_PRESETS]
        try:
            from roomkit_ui.settings import load_settings

            settings = load_settings()
            for att in json.loads(settings.get("custom_attitudes", "[]")):
                if att.get("name"):
                    available.append(att["name"])
        except (json.JSONDecodeError, TypeError):
            pass
        return json.dumps(
            {
                "error": f"Unknown attitude '{name}'.",
                "available": available,
            }
        )

    def _apply_attitude(self, name: str, description: str) -> str:
        """Apply a known attitude and update the live system prompt."""
        self._attitude = description
        self._attitude_name = name
        # Voice channel: update the system prompt on AIChannel for subsequent requests
        if self._ai_channel is not None:
            base = self._ai_channel._system_prompt or ""
            # Strip any existing attitude section
            if "\n\n# Attitude\n" in base:
                base = base.split("\n\n# Attitude\n")[0]
            if description:
                self._ai_channel._system_prompt = f"{base}\n\n# Attitude\n{description}"
            else:
                self._ai_channel._system_prompt = base
        try:
            self.attitude_changed.emit(self._attitude_name)
        except Exception:
            pass
        return json.dumps(
            {
                "status": "ok",
                "attitude": name,
                "instruction": f"Adopt this attitude now: {description}",
            }
        )

    @staticmethod
    def _paste_text(text: str) -> str:
        """Copy text to clipboard and simulate paste into the focused input."""
        if not text:
            return json.dumps({"error": "No text provided."})
        try:
            from roomkit_ui.stt_engine import _copy_to_clipboard, _simulate_paste

            _copy_to_clipboard(text)
            _simulate_paste()
            logger.info("paste_text: pasted %d chars", len(text))
            return json.dumps({"status": "ok", "chars": len(text)})
        except FileNotFoundError as exc:
            msg = f"Missing helper program: {exc.filename}"
            logger.error("paste_text: %s", msg)
            return json.dumps({"error": msg})
        except Exception as exc:
            msg = f"Paste failed: {exc}"
            logger.error("paste_text: %s", msg)
            return json.dumps({"error": msg})

    async def handle_app_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Proxy a tool call initiated by an MCP App back through MCP."""
        if self._mcp is None:
            return json.dumps({"error": "MCP not connected"})
        return await self._mcp.handle_tool_call(None, tool_name, arguments)

    # -- lifecycle -----------------------------------------------------------

    async def start(self, settings: dict) -> None:
        if self._state not in ("idle", "error"):
            return
        self._mic_muted = False

        mode = settings.get("conversation_mode", "realtime")
        if mode == "voice_channel":
            await self._start_voice_channel(settings)
        else:
            await self._start_realtime(settings)

    # -- Realtime (speech-to-speech) path ------------------------------------

    async def _start_realtime(self, settings: dict) -> None:
        self._state = "connecting"
        self.state_changed.emit("connecting")

        try:
            provider_name = settings.get("provider", "gemini")
            system_prompt = settings.get(
                "system_prompt",
                "You are a friendly voice assistant. Be concise and helpful.",
            )
            attitude = self._attitude or self._resolve_attitude(settings)
            if attitude:
                system_prompt = f"{system_prompt}\n\n# Attitude\n{attitude}"
                self._attitude = attitude
                if not self._attitude_name:
                    self._attitude_name = settings.get("selected_attitude", "") or attitude
            aec_mode = settings.get("aec_mode", "webrtc")
            denoise_mode = settings.get("denoise", "none")

            from roomkit import RealtimeVoiceChannel, RoomKit
            from roomkit.voice.realtime.local_transport import LocalAudioTransport

            provider: Any
            if provider_name == "openai":
                api_key = settings.get("openai_api_key", "")
                if not api_key:
                    raise ValueError("OpenAI API key is required. Open Settings to enter it.")
                model = settings.get("openai_model", "gpt-4o-realtime-preview")
                voice = settings.get("openai_voice", "alloy")
                from roomkit.providers.openai.realtime import OpenAIRealtimeProvider

                provider = OpenAIRealtimeProvider(api_key=api_key, model=model)
            else:
                api_key = settings.get("api_key", "")
                if not api_key:
                    raise ValueError("Google API key is required. Open Settings to enter it.")
                model = settings.get("model", "gemini-2.5-flash-native-audio-preview-12-2025")
                voice = settings.get("voice", "Aoede")
                from roomkit.providers.gemini.realtime import GeminiLiveProvider

                provider = GeminiLiveProvider(api_key=api_key, model=model)

            # Build provider_config for provider-specific advanced settings
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
                        eagerness = settings.get("openai_eagerness", "")
                        if eagerness:
                            try:
                                provider_config["eagerness"] = float(eagerness)
                            except (ValueError, TypeError):
                                pass
                    elif td_type == "server_vad":
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
                    if not settings.get("openai_interrupt_response", True):
                        provider_config["interrupt_response"] = False
                    if not settings.get("openai_create_response", True):
                        provider_config["create_response"] = False
                else:
                    # "none" — disable turn detection entirely
                    provider_config["turn_detection_type"] = None

            sample_rate = 24000
            block_ms = 20
            frame_size = sample_rate * block_ms // 1000

            aec, denoiser = self._build_audio_processing(
                aec_mode, denoise_mode, sample_rate, frame_size
            )

            mute_mic = aec is None

            input_device = settings.get("input_device")
            output_device = settings.get("output_device")

            # -- Diarization (optional) ------------------------------------------
            pipeline = None
            diarization: Any = None
            diarization_enabled = settings.get("diarization_enabled", False)
            diarization_model_id = settings.get("diarization_model", "")
            inference_device = settings.get("inference_device", "cpu")

            if diarization_enabled and diarization_model_id:
                from roomkit_ui.model_manager import (
                    build_diarization_config,
                    is_speaker_model_downloaded,
                )

                if is_speaker_model_downloaded(diarization_model_id):
                    from roomkit.voice.pipeline.diarization.sherpa_onnx import (
                        SherpaOnnxDiarizationProvider,
                    )

                    threshold = settings.get("diarization_threshold", 0.4)
                    if isinstance(threshold, str):
                        try:
                            threshold = float(threshold)
                        except (ValueError, TypeError):
                            threshold = 0.5
                    diar_key = ("diar", diarization_model_id, inference_device, threshold)
                    cached_diar = self._get_cached("diarization", diar_key)
                    if cached_diar is not None:
                        diarization = cached_diar
                        diarization.reset()
                        for name in list(diarization._manager.all_speakers):
                            diarization.remove_speaker(name)
                        diarization._enrolled_embeddings.clear()
                        logger.info("Diarization: reusing cached %s", diarization_model_id)
                    else:
                        self.loading_status.emit("Loading speaker model\u2026")
                        diar_config = build_diarization_config(
                            diarization_model_id,
                            provider=inference_device,
                            threshold=threshold,
                        )
                        diarization = SherpaOnnxDiarizationProvider(diar_config)
                        self._set_cached("diarization", diar_key, diarization)
                    self._diarization = diarization

                    # Load enrolled speakers
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

                    # Primary speaker mode
                    self._primary_speaker_mode = settings.get("primary_speaker_mode", False)
                    if self._primary_speaker_mode:
                        from roomkit_ui.speaker_manager import get_primary_speaker

                        primary = get_primary_speaker()
                        self._primary_speaker_name = primary.name if primary else ""

                    logger.info(
                        "Diarization: model=%s, threshold=%.2f, primary_mode=%s",
                        diarization_model_id,
                        threshold,
                        self._primary_speaker_mode,
                    )
                else:
                    logger.warning(
                        "Speaker model %s not downloaded — no diarization",
                        diarization_model_id,
                    )

            if diarization is not None:
                from roomkit.voice.pipeline.config import AudioPipelineConfig

                # Diarization needs VAD for speech boundary detection
                vad: Any = None
                vad_model_id = settings.get("vc_vad_model", "")
                if vad_model_id:
                    from roomkit_ui.model_manager import build_vad_config, is_vad_model_downloaded

                    if is_vad_model_downloaded(vad_model_id):
                        from roomkit.voice.pipeline.vad.sherpa_onnx import SherpaOnnxVADProvider

                        vad_config = build_vad_config(vad_model_id, provider=inference_device)
                        vad = SherpaOnnxVADProvider(vad_config)
                        logger.info("Realtime VAD: %s", vad_model_id)
                    else:
                        logger.warning("VAD model %s not downloaded — no VAD", vad_model_id)

                if vad is None:
                    logger.warning("Diarization requires VAD — skipping diarization")
                    diarization = None
                    self._diarization = None
                else:
                    from roomkit.voice.pipeline.config import (
                        AudioFormat,
                        AudioPipelineContract,
                    )

                    # Realtime providers use 24kHz; VAD/diarization models need 16kHz.
                    # No denoiser needed — the transport already denoises at 24kHz
                    # before audio reaches the pipeline.
                    contract = AudioPipelineContract(
                        transport_inbound_format=AudioFormat(sample_rate=sample_rate),
                        internal_format=AudioFormat(sample_rate=16000),
                    )
                    pipeline = AudioPipelineConfig(
                        vad=vad,
                        diarization=diarization,
                        contract=contract,
                    )

            # -- Transport -------------------------------------------------------
            transport = LocalAudioTransport(
                input_sample_rate=sample_rate,
                output_sample_rate=sample_rate,
                block_duration_ms=block_ms,
                mute_mic_during_playback=mute_mic,
                aec=aec,
                denoiser=denoiser,
                input_device=input_device,
                output_device=output_device,
                pipeline=pipeline,
            )

            self._transport = transport

            # Register speaker change callback directly on the transport
            if pipeline is not None:
                transport.on_speaker_change(self._on_transport_speaker_change)

            # Log audio pipeline configuration
            aec_label = type(aec).__name__ if aec else "none"
            denoise_label = type(denoiser).__name__ if denoiser else "none"
            logger.info(
                "Audio pipeline: aec=%s, denoiser=%s, rate=%dHz, block=%dms",
                aec_label,
                denoise_label,
                sample_rate,
                block_ms,
            )

            self._register_callbacks(provider, transport)

            # -- MCP tools -------------------------------------------------------
            mcp_servers_configured = False
            try:
                mcp_servers_configured = any(
                    s.get("enabled", True) for s in json.loads(settings.get("mcp_servers", "[]"))
                )
            except (json.JSONDecodeError, TypeError):
                pass
            if mcp_servers_configured:
                self.loading_status.emit("Connecting MCP servers\u2026")
            tools, has_mcp_tools = await self._setup_mcp_tools(settings)
            tool_handler = self._handle_tool_call

            all_names = ", ".join(t["name"] for t in tools)
            logger.info("Tools: %s", all_names)

            self.loading_status.emit("Connecting to provider\u2026")
            if provider_config:
                logger.info("provider_config: %s", provider_config)
            self._session = await self._start_session(
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
            )
            if self._session is None and has_mcp_tools:
                # MCP tools broke the session — retry without them
                logger.warning("Retrying session without MCP tools")
                self._session = await self._start_session(
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
                )
                if self._session is not None:
                    self.mcp_status.emit("MCP tools disabled — incompatible with this provider")
                    tools = list(BUILTIN_TOOLS)

            if self._session is None:
                raise RuntimeError("Failed to start voice session")

            register_realtime_hooks(self._kit, self)

            self._spk_rms_queue.clear()
            self._spk_timer.start()

            self._state = "active"
            self.state_changed.emit("active")

            # Emit structured session info for the UI info bar
            tool_info = [
                {"name": t.get("name", ""), "description": t.get("description", "")} for t in tools
            ]
            info: dict = {
                "provider": provider_name,
                "model": model,
                "tools": tool_info,
            }
            if self._mcp and self._mcp.failed_servers:
                info["failed_servers"] = list(self._mcp.failed_servers)
            self.session_info.emit(info)
            if self._attitude_name:
                self.attitude_changed.emit(self._attitude_name)

        except Exception as e:
            logger.exception("Failed to start voice session")
            self._state = "error"
            self.state_changed.emit("error")
            self.error_occurred.emit(str(e))
            await self._cleanup()

    # -- Voice Channel (STT → LLM → TTS) path -------------------------------

    async def _start_voice_channel(self, settings: dict) -> None:
        self._state = "connecting"
        self.state_changed.emit("connecting")

        try:
            from roomkit import RoomKit, VoiceChannel
            from roomkit.channels.ai import AIChannel
            from roomkit.voice.backends.local import LocalAudioBackend
            from roomkit.voice.pipeline.config import AudioPipelineConfig

            system_prompt = settings.get(
                "system_prompt",
                "You are a friendly voice assistant. Be concise and helpful.",
            )
            attitude = self._attitude or self._resolve_attitude(settings)
            if attitude:
                system_prompt = f"{system_prompt}\n\n# Attitude\n{attitude}"
                self._attitude = attitude
                if not self._attitude_name:
                    self._attitude_name = settings.get("selected_attitude", "") or attitude
            inference_device = settings.get("inference_device", "cpu")
            aec_mode = settings.get("aec_mode", "webrtc")
            denoise_mode = settings.get("denoise", "none")

            # 1. Build STT
            stt_provider_name = settings.get("vc_stt_provider", "local")
            stt_language = settings.get("stt_language", "") or "en"

            if stt_provider_name == "gradium":
                from roomkit.voice.stt.gradium import GradiumSTTConfig, GradiumSTTProvider

                self.loading_status.emit("Connecting Gradium STT\u2026")
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
                delay = settings.get("gradium_stt_delay", "")
                if delay:
                    try:
                        stt_kwargs["delay_in_frames"] = int(delay)
                    except (ValueError, TypeError):
                        pass
                vad_thresh = settings.get("gradium_vad_threshold", "")
                if vad_thresh:
                    try:
                        stt_kwargs["vad_threshold"] = float(vad_thresh)
                    except (ValueError, TypeError):
                        pass
                vad_steps = settings.get("gradium_vad_steps", "")
                if vad_steps:
                    try:
                        stt_kwargs["vad_steps"] = int(vad_steps)
                    except (ValueError, TypeError):
                        pass
                # json_config for STT temperature
                json_config: dict[str, Any] = {}
                stt_temp = settings.get("gradium_stt_temperature", "")
                if stt_temp:
                    try:
                        json_config["temperature"] = float(stt_temp)
                    except (ValueError, TypeError):
                        pass
                if json_config:
                    stt_kwargs["json_config"] = json_config
                stt_config = GradiumSTTConfig(
                    api_key=api_key,
                    region=region,
                    language=stt_language,
                    **stt_kwargs,
                )
                stt = GradiumSTTProvider(stt_config)
                logger.info("STT: gradium, region=%s, language=%s", region, stt_language)
            elif stt_provider_name == "deepgram":
                from roomkit.voice.stt.deepgram import DeepgramConfig, DeepgramSTTProvider

                self.loading_status.emit("Connecting Deepgram STT\u2026")
                api_key = settings.get("deepgram_api_key", "")
                if not api_key:
                    raise ValueError("Deepgram API key is required for Deepgram STT.")
                dg_model = settings.get("deepgram_model", "nova-3")
                dg_config = DeepgramConfig(
                    api_key=api_key,
                    model=dg_model,
                    language=stt_language,
                )
                stt = DeepgramSTTProvider(dg_config)
                logger.info("STT: deepgram, model=%s, language=%s", dg_model, stt_language)
            else:
                from roomkit.voice.stt.sherpa_onnx import SherpaOnnxSTTProvider

                from roomkit_ui.model_manager import build_stt_config

                stt_model_id = settings.get("vc_stt_model", "")
                if not stt_model_id:
                    raise ValueError(
                        "No STT model selected. Download one in AI Models"
                        " and select it in Settings."
                    )
                stt_translate = settings.get("stt_translate", False)
                stt_key = ("stt", stt_model_id, stt_language, stt_translate, inference_device)
                cached_stt = self._get_cached("stt", stt_key)
                if cached_stt is not None:
                    stt = cached_stt
                    logger.info("STT: reusing cached %s", stt_model_id)
                else:
                    self.loading_status.emit("Loading STT model\u2026")
                    local_stt_config = build_stt_config(
                        stt_model_id,
                        language=stt_language,
                        translate=stt_translate,
                        provider=inference_device,
                    )
                    stt = SherpaOnnxSTTProvider(local_stt_config)
                    logger.info("STT: model=%s, language=%s", stt_model_id, stt_language)
                    if hasattr(stt, "warmup"):
                        self.loading_status.emit("Warming up STT model\u2026")
                        await stt.warmup()
                    self._set_cached("stt", stt_key, stt)

            # Remote providers (gradium, deepgram) may also have warmup
            if stt_provider_name != "local" and hasattr(stt, "warmup"):
                self.loading_status.emit("Warming up STT\u2026")
                await stt.warmup()

            # 2. Build TTS
            tts_provider_name = settings.get("vc_tts_provider", "piper")
            tts_model_id = settings.get("vc_tts_model", "")
            tts_key = ("tts", tts_provider_name, tts_model_id, inference_device)
            cached_tts = self._get_cached("tts", tts_key)
            if cached_tts is not None:
                tts, output_sample_rate = cached_tts
                logger.info("TTS: reusing cached %s/%s", tts_provider_name, tts_model_id)
            else:
                self.loading_status.emit("Loading TTS model\u2026")
                tts, output_sample_rate = create_tts_provider(tts_provider_name, settings)
                if hasattr(tts, "warmup"):
                    self.loading_status.emit("Warming up TTS model\u2026")
                    await tts.warmup()
                # Cache local TTS providers (ONNX models are expensive to load)
                if tts_provider_name in ("piper", "qwen3", "neutts"):
                    self._set_cached("tts", tts_key, (tts, output_sample_rate))
            self._tts = tts
            logger.info(
                "TTS: provider=%s, sample_rate=%d",
                tts_provider_name,
                output_sample_rate,
            )

            # 3. Build AI provider
            self.loading_status.emit("Connecting to LLM\u2026")
            llm_provider_name = settings.get("vc_llm_provider", "anthropic")
            ai_provider = create_ai_provider(llm_provider_name, settings)
            model = ai_provider.model_name

            # Wrap local provider so "does not support tools" errors reach the UI
            if llm_provider_name == "local":
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
                                self.error_occurred.emit(
                                    "This model does not support tool use. "
                                    'Disable "Model supports tool use" in '
                                    "Settings \u2192 AI Provider."
                                )
                            except Exception:
                                pass
                        raise

                ai_provider.generate = _generate_with_tool_hint  # type: ignore[method-assign]

            # 4. Audio processing
            input_sample_rate = 16000
            block_ms = 20
            frame_size = input_sample_rate * block_ms // 1000

            aec, denoiser = self._build_audio_processing(
                aec_mode, denoise_mode, input_sample_rate, frame_size
            )

            # 5. Build audio backend
            input_device = settings.get("input_device")
            output_device = settings.get("output_device")

            backend = LocalAudioBackend(
                input_sample_rate=input_sample_rate,
                output_sample_rate=output_sample_rate,
                block_duration_ms=block_ms,
                input_device=input_device,
                output_device=output_device,
                aec=aec,
                mute_mic_during_playback=aec is None,
            )
            self._backend = backend

            aec_label = type(aec).__name__ if aec else "none"
            denoise_label = type(denoiser).__name__ if denoiser else "none"
            logger.info(
                "VC audio pipeline: aec=%s, denoiser=%s, in_rate=%dHz, out_rate=%dHz",
                aec_label,
                denoise_label,
                input_sample_rate,
                output_sample_rate,
            )

            # 6. Build pipeline config (with optional VAD — local STT only)
            vad: Any = None
            vad_model_id = settings.get("vc_vad_model", "") if stt_provider_name == "local" else ""
            if vad_model_id:
                from roomkit_ui.model_manager import build_vad_config, is_vad_model_downloaded

                if is_vad_model_downloaded(vad_model_id):
                    from roomkit.voice.pipeline.vad.sherpa_onnx import SherpaOnnxVADProvider

                    vad_config = build_vad_config(vad_model_id, provider=inference_device)
                    vad = SherpaOnnxVADProvider(vad_config)
                    logger.info("VAD: %s", vad_model_id)
                else:
                    logger.warning("VAD model %s not downloaded — no VAD", vad_model_id)

            # 6.5. Build diarization (optional — requires VAD)
            diarization: Any = None
            diarization_enabled = settings.get("diarization_enabled", False)
            diarization_model_id = settings.get("diarization_model", "")
            if diarization_enabled and diarization_model_id:
                from roomkit_ui.model_manager import (
                    build_diarization_config,
                    is_speaker_model_downloaded,
                )

                if not vad:
                    logger.warning("Diarization requires VAD — skipping")
                elif is_speaker_model_downloaded(diarization_model_id):
                    from roomkit.voice.pipeline.diarization.sherpa_onnx import (
                        SherpaOnnxDiarizationProvider,
                    )

                    threshold = settings.get("diarization_threshold", 0.4)
                    if isinstance(threshold, str):
                        try:
                            threshold = float(threshold)
                        except (ValueError, TypeError):
                            threshold = 0.5
                    diar_key = ("diar", diarization_model_id, inference_device, threshold)
                    cached_diar = self._get_cached("diarization", diar_key)
                    if cached_diar is not None:
                        diarization = cached_diar
                        diarization.reset()
                        # Clear and re-enroll speakers (enrollment may have changed)
                        for name in list(diarization._manager.all_speakers):
                            diarization.remove_speaker(name)
                        diarization._enrolled_embeddings.clear()
                        logger.info("Diarization: reusing cached %s", diarization_model_id)
                    else:
                        diar_config = build_diarization_config(
                            diarization_model_id,
                            provider=inference_device,
                            threshold=threshold,
                        )
                        self.loading_status.emit("Loading speaker model\u2026")
                        diarization = SherpaOnnxDiarizationProvider(diar_config)
                        self._set_cached("diarization", diar_key, diarization)
                    self._diarization = diarization

                    # Load enrolled speakers
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

                    # Primary speaker mode
                    self._primary_speaker_mode = settings.get("primary_speaker_mode", False)
                    if self._primary_speaker_mode:
                        from roomkit_ui.speaker_manager import get_primary_speaker

                        primary = get_primary_speaker()
                        self._primary_speaker_name = primary.name if primary else ""

                    logger.info(
                        "Diarization: model=%s, threshold=%.2f, primary_mode=%s",
                        diarization_model_id,
                        threshold,
                        self._primary_speaker_mode,
                    )
                else:
                    logger.warning(
                        "Speaker model %s not downloaded — no diarization",
                        diarization_model_id,
                    )

            # Interruption config
            from roomkit.voice.interruption import InterruptionConfig, InterruptionStrategy

            interruption_enabled = settings.get("vc_interruption", False)
            strategy = (
                InterruptionStrategy.IMMEDIATE
                if interruption_enabled
                else InterruptionStrategy.DISABLED
            )
            interruption = InterruptionConfig(strategy=strategy)
            logger.info("Interruption: %s", strategy.value)

            pipeline = AudioPipelineConfig(
                aec=aec,
                denoiser=denoiser,
                vad=vad,
                interruption=interruption,
                diarization=diarization,
            )

            # 7. Create VoiceChannel
            voice = VoiceChannel(
                "voice",
                stt=stt,
                tts=tts,
                backend=backend,
                pipeline=pipeline,
            )
            self._channel = voice

            # 7.5. Check if tools are supported (local models may not)
            skip_tools = llm_provider_name == "local" and not settings.get("vc_local_tools", True)

            # 7.6. Build skill registry from enabled skills
            skills_registry = None
            if not skip_tools:
                try:
                    from roomkit_ui.skill_manager import build_registry

                    sources = json.loads(settings.get("skill_sources", "[]"))
                    enabled = json.loads(settings.get("enabled_skills", "[]"))
                    if sources and enabled:
                        self.loading_status.emit("Loading skills\u2026")
                        skills_registry = build_registry(sources, enabled)
                        if skills_registry.skill_count > 0:
                            logger.info(
                                "Skills loaded: %s", ", ".join(skills_registry.skill_names)
                            )
                        else:
                            skills_registry = None
                except Exception:
                    logger.exception("Failed to load skills")

            # 8. Create AIChannel (with tool handler for MCP + built-in tools)
            async def _vc_tool_handler(name: str, arguments: dict[str, Any]) -> str:
                return await self._handle_tool_call(None, name, arguments)

            ai_channel = AIChannel(
                "ai",
                provider=ai_provider,
                system_prompt=system_prompt,
                tool_handler=_vc_tool_handler,
                skills=skills_registry,
            )
            self._ai_channel = ai_channel

            # 9. MCP tools (skip when the local model has no tool support)
            tools: list[dict] = []
            if skip_tools:
                logger.info("Local model tool support disabled — skipping MCP/tools")
            else:
                mcp_servers_configured = False
                try:
                    mcp_servers_configured = any(
                        s.get("enabled", True)
                        for s in json.loads(settings.get("mcp_servers", "[]"))
                    )
                except (json.JSONDecodeError, TypeError):
                    pass
                if mcp_servers_configured:
                    self.loading_status.emit("Connecting MCP servers\u2026")
                tools, _has_mcp = await self._setup_mcp_tools(settings)

            # 10. Wire up framework
            kit = RoomKit()
            self._kit = kit

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

            # 11. Register hooks for UI callbacks
            register_vc_hooks(kit, self)

            # 12. Connect and start
            self.loading_status.emit("Starting voice channel\u2026")
            session = await backend.connect("local-demo", "local-user", "voice")
            self._session = session
            voice.bind_session(session, "local-demo", voice_binding)
            await backend.start_listening(session)

            self._spk_rms_queue.clear()
            self._spk_timer.start()

            self._state = "active"
            self.state_changed.emit("active")

            # Emit session info
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
            if self._mcp and self._mcp.failed_servers:
                info["failed_servers"] = list(self._mcp.failed_servers)
            self.session_info.emit(info)
            if self._attitude_name:
                self.attitude_changed.emit(self._attitude_name)

        except Exception as e:
            logger.exception("Failed to start voice channel session")
            self._state = "error"
            self.state_changed.emit("error")
            self.error_occurred.emit(str(e))
            await self._cleanup()

    # -- Shared helpers ------------------------------------------------------

    @staticmethod
    def _resolve_attitude(settings: dict) -> str:
        """Resolve the selected attitude name to its text content."""
        name = settings.get("selected_attitude", "")
        if not name:
            return ""
        from roomkit_ui.widgets.settings.constants import ATTITUDE_PRESETS

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

    def _build_audio_processing(
        self,
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

        denoiser = self._build_denoiser(denoise_mode, sample_rate)
        return aec, denoiser

    @staticmethod
    def _build_denoiser(denoise_mode: str, sample_rate: int) -> Any:
        """Build a denoiser provider for the given mode and sample rate."""
        if denoise_mode == "rnnoise":
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
            else:
                logger.warning("GTCRN model not downloaded — denoiser disabled")
        return None

    async def _setup_mcp_tools(self, settings: dict) -> tuple[list[dict], bool]:
        """Connect MCP servers and return (tools_list, has_mcp_tools)."""
        mcp_servers: list[dict] = []
        try:
            mcp_servers = [
                s for s in json.loads(settings.get("mcp_servers", "[]")) if s.get("enabled", True)
            ]
        except (json.JSONDecodeError, TypeError):
            pass

        tools: list[dict] = list(BUILTIN_TOOLS)

        if mcp_servers:
            self._mcp = MCPManager(mcp_servers)
            await self._mcp.connect_all()
            discovered = self._mcp.get_tools()

            if self._mcp.failed_servers:
                failed = ", ".join(self._mcp.failed_servers)
                self.mcp_status.emit(f"MCP failed: {failed}")

            if discovered:
                tools.extend(discovered)
                names = ", ".join(t["name"] for t in discovered)
                logger.info("MCP tools: %s", names)

        has_mcp_tools = len(tools) > len(BUILTIN_TOOLS)
        return tools, has_mcp_tools

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
    ) -> Any:
        """Try to create a room and start a session. Returns None on failure."""
        try:
            self._kit = RoomKit()
            self._channel = RealtimeVoiceChannel(
                "voice",
                provider=provider,
                transport=transport,
                system_prompt=system_prompt,
                voice=voice,
                input_sample_rate=sample_rate,
                tools=tools,
                tool_handler=tool_handler,
            )
            self._kit.register_channel(self._channel)
            await self._kit.create_room(room_id="local-demo")
            await self._kit.attach_channel("local-demo", "voice")
            metadata = {"provider_config": provider_config} if provider_config else None
            return await self._channel.start_session(
                "local-demo",
                "local-user",
                connection=None,
                metadata=metadata,
            )
        except Exception:
            logger.exception("_start_session failed")
            try:
                await self._kit.close()
            except Exception:
                pass
            self._kit = None
            self._channel = None
            return None

    async def stop(self) -> None:
        if self._state not in ("active", "connecting", "error"):
            return
        try:
            await self._cleanup()
        except Exception:
            logger.exception("Error during stop")
        finally:
            self._attitude = ""
            self._attitude_name = ""
            self._log_handler._last_msg = ""
            self._state = "idle"
            self.state_changed.emit("idle")

    async def _cleanup(self) -> None:
        self._spk_timer.stop()
        self._spk_rms_queue.clear()
        # Cancel any lingering post_cleanup_monitor from previous session
        if self._cleanup_monitor_task is not None:
            self._cleanup_monitor_task.cancel()
            self._cleanup_monitor_task = None
        # Voice channel mode: disconnect backend
        if self._backend and self._session:
            try:
                logger.info("cleanup: disconnecting voice channel backend …")
                await self._backend.stop_listening(self._session)
                await self._backend.disconnect(self._session)
                logger.info("cleanup: backend disconnected")
            except Exception:
                logger.exception("cleanup: backend disconnect failed")
        # Realtime mode: end session via channel
        elif self._channel and self._session and not self._backend:
            try:
                logger.info("cleanup: ending voice session …")
                await self._channel.end_session(self._session)
                logger.info("cleanup: voice session ended")
            except Exception:
                logger.exception("cleanup: end_session failed")
        # Skip close for cached TTS (model survives for next session)
        if (
            self._tts is not None
            and hasattr(self._tts, "close")
            and "tts" not in self._cached_models
        ):
            try:
                await self._tts.close()
            except Exception:
                logger.exception("cleanup: tts.close() failed")
        if self._backend:
            try:
                await self._backend.close()
            except Exception:
                logger.exception("cleanup: backend.close() failed")
        # Detach STT/TTS/backend from the channel — the Engine handles their
        # lifecycle directly.  Without this, VoiceChannel.close() would
        # double-close them (e.g. ElevenLabs httpx client hang on second
        # aclose, or backend.close() called twice).
        if self._channel:
            try:
                self._channel._stt = None
                self._channel._tts = None
                self._channel._backend = None
            except Exception:
                pass
        if self._kit:
            try:
                logger.info("cleanup: closing roomkit …")
                await self._kit.close()
                logger.info("cleanup: roomkit closed")
            except Exception:
                logger.exception("cleanup: kit.close() failed")
        if self._mcp:
            try:
                logger.info("cleanup: closing MCP …")
                await self._mcp.close_all()
                logger.info("cleanup: MCP closed")
            except Exception:
                logger.exception("cleanup: mcp.close_all() failed")
        # Skip close for cached diarization (extractor survives)
        if self._diarization is not None and "diarization" not in self._cached_models:
            try:
                self._diarization.close()
            except Exception:
                pass
        self._channel = None
        self._ai_channel = None
        self._session = None
        self._kit = None
        self._transport = None
        self._backend = None
        self._tts = None
        self._mcp = None
        self._diarization = None
        self._current_speaker_id = ""
        self._primary_speaker_mode = False
        self._primary_speaker_name = ""
        # Note: self._attitude is preserved across reconnects and only
        # cleared in stop() when the user explicitly ends the session.

        # --- Task finalization ---
        # kit.close() cancels VoiceChannel's scheduled tasks, but they
        # need event-loop iterations to actually finalize (receive
        # CancelledError).  Yield here so they can complete before we
        # run cleanup_stale_fds() — otherwise cleanup kills the timer
        # handles those tasks need, leaving them stuck in "cancelling"
        # state forever and accumulating across sessions.
        await asyncio.sleep(0)

        # Cancel any remaining session tasks that didn't finalize
        current = asyncio.current_task()
        _session_task_names = (
            "speech_end",
            "_play_stream",
            "speaker_change",
            "audio_level",
            "barge_in",
            "speech_start",
            "session_started",
            "vad_silence",
            "_process_target",
            "EventRouter",
        )
        for task in list(asyncio.all_tasks()):
            if task is current or task.done():
                continue
            name = task.get_name() or ""
            if any(k in name for k in _session_task_names):
                logger.info("cleanup: cancelling lingering task: %s", name)
                task.cancel()

        # Second yield to let freshly-cancelled tasks finalize
        await asyncio.sleep(0)

        # Now safe to clean up stale event-loop state left by MCP/anyio.
        cleanup_stale_fds()
        # The orphaned anyio timers may only appear after the current
        # event-loop iteration completes (they re-create themselves via
        # call_soon).  Schedule a delayed second pass to catch them
        # without interfering with ongoing task finalization.
        asyncio.get_event_loop().call_later(0.1, cleanup_stale_fds)
        # Monitor CPU after cleanup to verify the fix worked
        self._cleanup_monitor_task = asyncio.ensure_future(post_cleanup_monitor())

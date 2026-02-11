"""Async engine wrapping roomkit — emits Qt signals for the UI."""

from __future__ import annotations

import collections
import datetime
import json
import logging
import math
import struct
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from room_ui.mcp_manager import MCPManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

# 24 kHz, 16-bit mono → 960 bytes per 20 ms block
_BLOCK_BYTES = 960


def _compute_rms(data: bytes) -> float:
    """Return RMS level 0.0-1.0 from 16-bit PCM audio bytes.

    Uses a square-root curve so quiet mic signals are still clearly visible
    on the VU meter while loud signals don't clip too aggressively.
    """
    if len(data) < 2:
        return 0.0
    n = len(data) // 2
    samples = struct.unpack(f"<{n}h", data)
    rms = math.sqrt(sum(s * s for s in samples) / n) / 32768.0
    # sqrt curve: quiet speech (~0.03) → 0.55, loud speech (~0.15) → 1.0
    return min(1.0, math.sqrt(rms) * 3.2)


# ---------------------------------------------------------------------------
# Built-in tools (always available)
# ---------------------------------------------------------------------------

_BUILTIN_TOOLS = [
    {
        "type": "function",
        "name": "get_current_date",
        "description": "Get today's date and day of the week.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "get_current_time",
        "description": "Get the current local time.",
        "parameters": {"type": "object", "properties": {}},
    },
]


def _handle_builtin_tool(name: str) -> str | None:
    """Handle a built-in tool call. Returns JSON string or None if not built-in."""
    now = datetime.datetime.now()
    if name == "get_current_date":
        return json.dumps(
            {
                "date": now.strftime("%Y-%m-%d"),
                "day": now.strftime("%A"),
            }
        )
    if name == "get_current_time":
        return json.dumps(
            {
                "time": now.strftime("%H:%M:%S"),
                "timezone": now.astimezone().tzname(),
            }
        )
    return None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class Engine(QObject):
    """Manages a roomkit voice session and bridges events to Qt signals."""

    state_changed = Signal(str)  # idle / connecting / active / error
    transcription = Signal(str, str, bool)  # text, role, is_final
    mic_audio_level = Signal(float)  # 0.0-1.0
    speaker_audio_level = Signal(float)  # 0.0-1.0
    user_speaking = Signal(bool)
    ai_speaking = Signal(bool)
    error_occurred = Signal(str)
    tool_use = Signal(str, str)  # tool_name, arguments_json
    mcp_status = Signal(str)  # status message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._kit: Any = None
        self._channel: Any = None
        self._session: Any = None
        self._transport: Any = None
        self._mcp: MCPManager | None = None
        self._mic_muted = False
        self._state = "idle"

        # Speaker RMS queue: audio arrives in bursts from the provider but
        # plays back at a steady 20 ms cadence.  We split incoming chunks
        # into block-sized RMS values and drain them with a timer that
        # matches the real playback rate.
        self._spk_rms_queue: collections.deque[float] = collections.deque()
        self._spk_timer = QTimer(self)
        self._spk_timer.setInterval(20)  # one playback block
        self._spk_timer.timeout.connect(self._drain_speaker_level)

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

    # -- register our own callbacks (roomkit uses append-based lists) --------

    def _register_callbacks(self, provider: Any, transport: Any) -> None:
        provider.on_transcription(self._on_transcription)
        provider.on_audio(self._on_speaker_audio)
        provider.on_speech_start(self._on_speech_start)
        provider.on_speech_end(self._on_speech_end)
        provider.on_response_start(self._on_response_start)
        provider.on_response_end(self._on_response_end)
        provider.on_error(self._on_provider_error)
        transport.on_audio_received(self._on_mic_audio)

    # -- callbacks -----------------------------------------------------------

    def _on_transcription(self, _s: Any, text: str, role: str, is_final: bool) -> None:
        try:
            self.transcription.emit(str(text), str(role), bool(is_final))
        except Exception:
            pass

    def _on_speaker_audio(self, _s: Any, audio: bytes) -> None:
        """Split provider audio into block-sized RMS values and queue them."""
        try:
            offset = 0
            while offset + _BLOCK_BYTES <= len(audio):
                block = audio[offset : offset + _BLOCK_BYTES]
                self._spk_rms_queue.append(_compute_rms(block))
                offset += _BLOCK_BYTES
            if offset < len(audio):
                self._spk_rms_queue.append(_compute_rms(audio[offset:]))
        except Exception:
            pass

    def _drain_speaker_level(self) -> None:
        """Pop one RMS value per timer tick → matches real playback cadence."""
        if self._spk_rms_queue:
            self.speaker_audio_level.emit(self._spk_rms_queue.popleft())

    def _on_mic_audio(self, _s: Any, audio: bytes) -> None:
        try:
            if self._mic_muted:
                self.mic_audio_level.emit(0.0)
            else:
                self.mic_audio_level.emit(_compute_rms(audio))
        except Exception:
            pass

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
        try:
            self.error_occurred.emit(f"{code}: {message}")
        except Exception:
            pass

    # -- tool calls ----------------------------------------------------------

    async def _handle_tool_call(
        self,
        session: Any,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Handle built-in tools or forward to MCP manager."""
        try:
            self.tool_use.emit(name, json.dumps(arguments))
        except Exception:
            pass

        # Try built-in tools first
        builtin_result = _handle_builtin_tool(name)
        if builtin_result is not None:
            return builtin_result

        if self._mcp is None:
            return '{"error": "Unknown tool"}'
        return await self._mcp.handle_tool_call(session, name, arguments)

    # -- lifecycle -----------------------------------------------------------

    async def start(self, settings: dict) -> None:
        if self._state not in ("idle", "error"):
            return
        self._mic_muted = False

        self._state = "connecting"
        self.state_changed.emit("connecting")

        try:
            provider_name = settings.get("provider", "gemini")
            system_prompt = settings.get(
                "system_prompt",
                "You are a friendly voice assistant. Be concise and helpful.",
            )
            aec_mode = settings.get("aec_mode", "webrtc")
            use_denoise = settings.get("denoise", False)

            from roomkit import RealtimeVoiceChannel, RoomKit
            from roomkit.voice.realtime.local_transport import LocalAudioTransport

            self._kit = RoomKit()

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

            sample_rate = 24000
            block_ms = 20
            frame_size = sample_rate * block_ms // 1000

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

            denoiser = None
            if use_denoise:
                try:
                    from roomkit.voice.pipeline.denoiser.rnnoise import RNNoiseDenoiserProvider

                    denoiser = RNNoiseDenoiserProvider(sample_rate=sample_rate)
                except ImportError:
                    logger.warning("RNNoise denoiser not available")

            mute_mic = aec is None

            input_device = settings.get("input_device")
            output_device = settings.get("output_device")

            transport = LocalAudioTransport(
                input_sample_rate=sample_rate,
                output_sample_rate=sample_rate,
                block_duration_ms=block_ms,
                mute_mic_during_playback=mute_mic,
                aec=aec,
                denoiser=denoiser,
                input_device=input_device,
                output_device=output_device,
            )

            self._transport = transport
            self._register_callbacks(provider, transport)

            # -- MCP tools -------------------------------------------------------
            mcp_servers: list[dict] = []
            try:
                mcp_servers = json.loads(settings.get("mcp_servers", "[]"))
            except (json.JSONDecodeError, TypeError):
                pass

            # Always start with built-in tools
            tools: list[dict] = list(_BUILTIN_TOOLS)
            tool_handler = self._handle_tool_call

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
                    self.mcp_status.emit(f"MCP tools: {names}")
                elif not self._mcp.failed_servers:
                    self.mcp_status.emit("MCP: no tools available")

            all_names = ", ".join(t["name"] for t in tools)
            logger.info("Tools: %s", all_names)

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

            self._session = await self._channel.start_session(
                "local-demo",
                "local-user",
                connection=None,
            )

            self._spk_rms_queue.clear()
            self._spk_timer.start()

            self._state = "active"
            self.state_changed.emit("active")
            logger.info("Voice session started")

        except Exception as e:
            logger.exception("Failed to start voice session")
            self._state = "error"
            self.state_changed.emit("error")
            self.error_occurred.emit(str(e))
            await self._cleanup()

    async def stop(self) -> None:
        if self._state not in ("active", "connecting", "error"):
            return
        try:
            await self._cleanup()
        except Exception:
            logger.exception("Error during stop")
        finally:
            self._state = "idle"
            self.state_changed.emit("idle")

    async def _cleanup(self) -> None:
        self._spk_timer.stop()
        self._spk_rms_queue.clear()
        if self._channel and self._session:
            try:
                await self._channel.end_session(self._session)
            except Exception:
                pass
        if self._kit:
            try:
                await self._kit.close()
            except Exception:
                pass
        if self._mcp:
            try:
                await self._mcp.close_all()
            except Exception:
                pass
        self._channel = None
        self._session = None
        self._kit = None
        self._transport = None
        self._mcp = None

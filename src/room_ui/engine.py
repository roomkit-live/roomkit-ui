"""Async engine wrapping roomkit — emits Qt signals for the UI."""

from __future__ import annotations

import collections
import logging
import math
import struct
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

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
# Engine
# ---------------------------------------------------------------------------

class Engine(QObject):
    """Manages a roomkit voice session and bridges events to Qt signals."""

    state_changed = Signal(str)            # idle / connecting / active / error
    transcription = Signal(str, str, bool)  # text, role, is_final
    mic_audio_level = Signal(float)        # 0.0-1.0
    speaker_audio_level = Signal(float)    # 0.0-1.0
    user_speaking = Signal(bool)
    ai_speaking = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._kit: Any = None
        self._channel: Any = None
        self._session: Any = None
        self._transport: Any = None
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
        # Pause / resume the PortAudio input stream directly.
        # This is the cleanest way to mute — no audio frames are captured
        # at all, so nothing reaches the provider.
        if self._transport is not None:
            try:
                for stream in self._transport._input_streams.values():
                    if muted and stream.active:
                        stream.stop()
                    elif not muted and not stream.active:
                        stream.start()
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

            aec = None
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

            self._channel = RealtimeVoiceChannel(
                "voice",
                provider=provider,
                transport=transport,
                system_prompt=system_prompt,
                voice=voice,
                input_sample_rate=sample_rate,
            )
            self._kit.register_channel(self._channel)

            await self._kit.create_room(room_id="local-demo")
            await self._kit.attach_channel("local-demo", "voice")

            self._session = await self._channel.start_session(
                "local-demo", "local-user", connection=None,
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
        self._channel = None
        self._session = None
        self._kit = None
        self._transport = None

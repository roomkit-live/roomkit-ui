"""STT engine — records speech via a roomkit STT room and pastes transcribed text."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from typing import Any

from PySide6.QtCore import QObject, Signal

from room_ui.settings import load_settings

logger = logging.getLogger(__name__)


def _is_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def _copy_to_clipboard(text: str) -> None:
    """Copy *text* to the system clipboard."""
    if _is_wayland():
        subprocess.run(
            ["wl-copy", "--", text],
            check=True,
            timeout=5,
        )
    else:
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode(),
            check=True,
            timeout=5,
        )


def _simulate_paste() -> None:
    """Simulate Ctrl+V to paste clipboard contents into the focused window."""
    if _is_wayland():
        subprocess.run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"], check=True, timeout=5)
    else:
        subprocess.run(["xdotool", "key", "ctrl+v"], check=True, timeout=5)


class STTEngine(QObject):
    """Records speech via an OpenAI Realtime STT room and pastes the result.

    Uses a dedicated roomkit room (``stt-room``) with
    ``create_response=False`` so the provider only transcribes — no AI
    response is generated.
    """

    recording_changed = Signal(bool)
    text_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._recording = False
        self._kit: Any = None
        self._channel: Any = None
        self._session: Any = None
        self._provider: Any = None
        self._accumulated_text: list[str] = []
        self._transcription_event: asyncio.Event | None = None

    @property
    def recording(self) -> bool:
        return self._recording

    def toggle_recording(self) -> None:
        if self._recording:
            asyncio.ensure_future(self._stop_recording())
        else:
            asyncio.ensure_future(self._start_recording())

    # -- transcription callback ------------------------------------------------

    def _on_transcription(
        self, _session: Any, text: str, role: str, is_final: bool
    ) -> None:
        if role == "user" and is_final and text.strip():
            logger.info("STT transcription (final): %s", text)
            self._accumulated_text.append(text.strip())
            if self._transcription_event is not None:
                self._transcription_event.set()

    # -- lifecycle -------------------------------------------------------------

    async def _start_recording(self) -> None:
        if self._recording:
            return

        self._recording = True
        self.recording_changed.emit(True)
        self._accumulated_text.clear()

        # --- Fake mode: skip roomkit, just use hardcoded text ---
        if os.environ.get("STT_FAKE"):
            logger.info("STT fake mode — will paste test text on stop")
            return

        settings = load_settings()
        api_key = settings.get("openai_api_key", "")
        if not api_key:
            self.error_occurred.emit(
                "OpenAI API key is required for dictation. Open Settings to enter it."
            )
            self._recording = False
            self.recording_changed.emit(False)
            return

        try:
            from roomkit import RealtimeVoiceChannel, RoomKit
            from roomkit.providers.openai.realtime import OpenAIRealtimeProvider
            from roomkit.voice.realtime.local_transport import LocalAudioTransport

            self._kit = RoomKit()

            self._provider = OpenAIRealtimeProvider(
                api_key=api_key,
                model=settings.get("openai_model", "gpt-4o-realtime-preview"),
            )
            self._provider.on_transcription(self._on_transcription)
            provider = self._provider

            sample_rate = 24000
            input_device = settings.get("input_device")

            transport = LocalAudioTransport(
                input_sample_rate=sample_rate,
                output_sample_rate=sample_rate,
                block_duration_ms=20,
                mute_mic_during_playback=False,
                input_device=input_device,
            )

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
                import json
                ws = self._provider._connections.get(self._session.id)
                if ws:
                    await ws.send(json.dumps({
                        "type": "session.update",
                        "session": {
                            "input_audio_transcription": {
                                "model": "gpt-4o-transcribe",
                                "language": stt_language,
                            },
                        },
                    }))
                    logger.info("Set STT language: %s", stt_language)

            logger.info("STT session started")

        except Exception as exc:
            logger.exception("Failed to start STT session")
            self._recording = False
            self.recording_changed.emit(False)
            self.error_occurred.emit(str(exc))
            await self._cleanup()

    async def _stop_recording(self) -> None:
        if not self._recording:
            return

        self._recording = False
        self.recording_changed.emit(False)
        logger.info("STT recording stopped")

        if os.environ.get("STT_FAKE"):
            self._accumulated_text.append("Hello, this is a test transcription.")
        else:
            # Commit any buffered audio so OpenAI returns the transcription
            # before we tear down the session.
            await self._commit_and_wait()

        # Emit / paste the text BEFORE cleanup (cleanup is slow).
        text = " ".join(self._accumulated_text).strip()
        if text:
            logger.info("Emitting text_ready: %s", text[:80])
            # Small delay so the hotkey release doesn't interfere with pasting.
            await asyncio.sleep(0.15)
            self.text_ready.emit(text)
        else:
            logger.info("No transcription captured")

        if not os.environ.get("STT_FAKE"):
            try:
                await self._cleanup()
            except Exception:
                logger.exception("Error during STT cleanup")

    async def _commit_and_wait(self) -> None:
        """Send input_audio_buffer.commit and wait for the transcription."""
        import json

        if self._provider is None or self._session is None:
            return

        ws = self._provider._connections.get(self._session.id)
        if ws is None:
            return

        self._transcription_event = asyncio.Event()
        # If we already have text from earlier VAD cycles, pre-set the event
        # so we don't block unnecessarily.
        if self._accumulated_text:
            self._transcription_event.set()

        try:
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            logger.info("Sent input_audio_buffer.commit, waiting for transcription...")
        except Exception:
            logger.exception("Error sending audio buffer commit")
            self._transcription_event = None
            return

        try:
            await asyncio.wait_for(self._transcription_event.wait(), timeout=5.0)
            logger.info("Transcription ready")
        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for transcription after commit")
        finally:
            self._transcription_event = None

    async def _cleanup(self) -> None:
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
        self._provider = None
        self._kit = None

    # -- paste -----------------------------------------------------------------

    def paste_text(self, text: str) -> None:
        """Copy *text* to clipboard and simulate Ctrl+V."""
        try:
            logger.info("Pasting text: %s", text[:80])
            _copy_to_clipboard(text)
            _simulate_paste()
            logger.info("Paste succeeded")
        except FileNotFoundError as exc:
            msg = (
                f"Missing helper program: {exc.filename}. "
                "Install xclip+xdotool (X11) or wl-copy+wtype (Wayland)."
            )
            logger.error(msg)
            self.error_occurred.emit(msg)
        except subprocess.SubprocessError as exc:
            msg = f"Paste failed: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)

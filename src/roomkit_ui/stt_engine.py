"""STT engine — records speech via a roomkit STT room and pastes transcribed text."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from typing import Any

from PySide6.QtCore import QObject, Signal

from roomkit_ui.paste import (
    _activate_bundle,
    _copy_to_clipboard,
    _get_frontmost_bundle,
    _simulate_paste,
)
from roomkit_ui.settings import load_settings
from roomkit_ui.stt_sessions import DictationSessionMixin

# Re-exported for backward compatibility with any code that still does
# ``from roomkit_ui.stt_engine import _copy_to_clipboard``.  New callers
# should import from ``roomkit_ui.paste`` directly.
__all__ = [
    "STTEngine",
    "_activate_bundle",
    "_copy_to_clipboard",
    "_get_frontmost_bundle",
    "_simulate_paste",
]

logger = logging.getLogger(__name__)


class STTEngine(DictationSessionMixin, QObject):
    """Records speech via a roomkit STT room and pastes the result.

    Supports two providers:
    - **OpenAI**: ``RealtimeVoiceChannel`` with ``create_response=False``
    - **Local**: ``VoiceChannel`` with ``SherpaOnnxSTTProvider`` + ``LocalAudioBackend``
    """

    recording_changed = Signal(bool)
    text_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._recording = False
        self._busy = False  # guards against overlapping start/stop
        self._kit: Any = None
        self._channel: Any = None
        self._session: Any = None
        self._provider: Any = None
        self._transport: Any = None
        self._accumulated_text: list[str] = []
        self._transcription_event: asyncio.Event | None = None
        self._prev_app: str | None = None  # bundle ID of app that was focused before recording
        # Local STT state (VoiceChannel + LocalAudioBackend)
        self._local_provider: Any = None
        self._local_backend: Any = None
        self._local_session: Any = None
        self._local_flush_event: asyncio.Event | None = None
        self._batch_mode: bool = False

    @property
    def recording(self) -> bool:
        return self._recording

    def toggle_recording(self) -> None:
        logger.info(
            "toggle_recording: recording=%s busy=%s",
            self._recording,
            self._busy,
        )
        if self._recording:
            asyncio.ensure_future(self._stop_recording())
        else:
            asyncio.ensure_future(self._start_recording())

    # -- transcription callback ------------------------------------------------

    def _on_transcription(self, _session: Any, text: str, role: str, is_final: bool) -> None:
        if role == "user" and is_final and text.strip():
            logger.info("STT transcription final: %d chars", len(text))
            logger.debug("STT transcription final text: %s", text)
            self._accumulated_text.append(text.strip())
            if self._transcription_event is not None:
                self._transcription_event.set()

    # -- lifecycle -------------------------------------------------------------

    async def _start_recording(self) -> None:
        if self._recording or self._busy:
            logger.warning(
                "_start_recording skipped: recording=%s busy=%s",
                self._recording,
                self._busy,
            )
            return

        self._busy = True
        self._recording = True
        self.recording_changed.emit(True)
        self._accumulated_text.clear()
        self._prev_app = _get_frontmost_bundle()
        logger.info("Saved frontmost app: %s", self._prev_app)

        # --- Fake mode: skip roomkit, just use hardcoded text ---
        if os.environ.get("STT_FAKE"):
            logger.info("STT fake mode — will paste test text on stop")
            self._busy = False
            return

        settings = load_settings()
        stt_provider = settings.get("stt_provider", "openai")

        if stt_provider == "local":
            await self._start_local_recording(settings)
        elif stt_provider == "deepgram":
            await self._start_deepgram_recording(settings)
        else:
            await self._start_openai_recording(settings)

    def _fail_start(self, message: str) -> None:
        """Abort start-recording cleanly (pre-try paths: nothing to clean up).

        Emits the error on the UI signal and restores idle state so the
        hotkey can trigger again.  Also clears ``self._busy`` because no
        subsequent ``finally`` will run after a guard-clause return.
        """
        self.error_occurred.emit(message)
        self._recording = False
        self._busy = False
        self.recording_changed.emit(False)

    async def _stop_recording(self) -> None:
        if not self._recording:
            return
        if self._busy:
            # Start is still in progress; just flag recording off so it
            # won't continue once start finishes.
            self._recording = False
            self.recording_changed.emit(False)
            return

        self._recording = False
        self.recording_changed.emit(False)
        logger.info("STT recording stopped")

        try:
            if os.environ.get("STT_FAKE"):
                self._accumulated_text.append("Hello, this is a test transcription.")
            elif self._local_provider is not None:
                await self._stop_local_recording()
            else:
                # Only commit if we don't already have text from VAD —
                # committing an empty buffer causes a harmless but noisy error.
                if not self._accumulated_text:
                    await self._commit_and_wait()

            # Emit / paste the text BEFORE cleanup (cleanup is slow).
            text = " ".join(self._accumulated_text).strip()
            if text:
                logger.info("Emitting text_ready: %d chars", len(text))
                logger.debug("text_ready payload: %s", text)
                # Restore focus to the app that was active before recording,
                # then give it a moment to come forward before pasting.
                if self._prev_app:
                    _activate_bundle(self._prev_app)
                    await asyncio.sleep(0.25)
                else:
                    await asyncio.sleep(0.15)
                self.text_ready.emit(text)
            else:
                logger.info("No transcription captured")
        finally:
            # Snapshot the objects and clear self._ immediately so a new
            # recording cycle won't be affected by the background cleanup.
            if self._local_provider is not None:
                self._cleanup_local()
            elif not os.environ.get("STT_FAKE"):
                snap = (self._kit, self._channel, self._session, self._transport)
                self._kit = None
                self._channel = None
                self._session = None
                self._provider = None
                self._transport = None
                asyncio.ensure_future(self._cleanup_snapshot(*snap))

    async def _stop_local_recording(self) -> None:
        """Stop the LocalAudioBackend and wait for final transcriptions."""
        if self._local_backend and self._local_session:
            await self._local_backend.stop_listening(self._local_session)

            if self._batch_mode:
                # Batch mode: flush accumulated audio through offline STT
                try:
                    result = await asyncio.wait_for(
                        self._channel.flush_stt(self._local_session),
                        timeout=30.0,
                    )
                    if result and result.text and result.text.strip():
                        logger.info("Batch STT result: %d chars", len(result.text))
                        logger.debug("Batch STT text: %s", result.text)
                        self._accumulated_text.append(result.text.strip())
                except TimeoutError:
                    logger.warning("Batch STT timed out")
            else:
                # Streaming mode: wait for final transcription from hook
                if self._local_flush_event is not None:
                    self._local_flush_event.clear()
                    try:
                        await asyncio.wait_for(self._local_flush_event.wait(), timeout=3.0)
                    except TimeoutError:
                        logger.info("No final transcription received within timeout")

    def _cleanup_local(self) -> None:
        """Snapshot and clear local STT state, schedule async cleanup."""
        snap = (self._kit, self._channel, self._local_backend, self._local_session)
        self._kit = None
        self._channel = None
        self._local_provider = None
        self._local_backend = None
        self._local_session = None
        self._local_flush_event = None
        self._batch_mode = False
        if any(snap):
            asyncio.ensure_future(self._cleanup_local_snapshot(*snap))

    async def _cleanup_local_snapshot(
        self, kit: Any, channel: Any, backend: Any, session: Any
    ) -> None:
        """Clean up local STT objects without touching self._."""
        try:
            if channel and session:
                try:
                    channel.unbind_session(session)
                except Exception:
                    pass
            if backend and session:
                try:
                    await backend.disconnect(session)
                except Exception:
                    pass
            if kit:
                try:
                    await kit.close()
                except Exception:
                    pass
        except Exception:
            logger.exception("Error during local STT cleanup")

    async def _commit_and_wait(self) -> None:
        """Send input_audio_buffer.commit and wait for the transcription."""
        if self._provider is None or self._session is None:
            return

        self._transcription_event = asyncio.Event()
        # If we already have text from earlier VAD cycles, pre-set the event
        # so we don't block unnecessarily.
        if self._accumulated_text:
            self._transcription_event.set()

        try:
            await self._provider.send_event(self._session, {"type": "input_audio_buffer.commit"})
            logger.info("Sent input_audio_buffer.commit, waiting for transcription...")
        except Exception:
            logger.exception("Error sending audio buffer commit")
            self._transcription_event = None
            return

        try:
            await asyncio.wait_for(self._transcription_event.wait(), timeout=5.0)
            logger.info("Transcription ready")
        except TimeoutError:
            logger.warning("Timed out waiting for transcription after commit")
        finally:
            self._transcription_event = None

    async def _cleanup_snapshot(
        self,
        kit: Any,
        channel: Any,
        session: Any,
        transport: Any,
    ) -> None:
        """Clean up a previous session's objects without touching self._."""
        try:
            if channel and session:
                try:
                    await channel.end_session(session)
                except Exception:
                    pass
            if kit:
                try:
                    await kit.close()
                except Exception:
                    pass
        except Exception:
            logger.exception("Error during STT cleanup")

    async def _cleanup(self) -> None:
        """Cleanup using self._ — only used on start failure."""
        await self._cleanup_snapshot(
            self._kit,
            self._channel,
            self._session,
            self._transport,
        )
        self._kit = None
        self._channel = None
        self._session = None
        self._provider = None
        self._transport = None

    # -- paste -----------------------------------------------------------------

    def paste_text(self, text: str) -> None:
        """Copy *text* to clipboard and simulate Ctrl+V.

        Runs blocking subprocess calls in a thread pool to avoid freezing
        the event loop (clipboard copy/paste can block up to 5 seconds).
        """

        async def _paste_async() -> None:
            try:
                loop = asyncio.get_running_loop()
                front = _get_frontmost_bundle()
                logger.info("Pasting text to %s: %d chars", front or "(self)", len(text))
                logger.debug("Paste text payload: %s", text)
                await loop.run_in_executor(None, _copy_to_clipboard, text)
                ok = await loop.run_in_executor(None, _simulate_paste)
                if not ok:
                    msg = (
                        "Accessibility permission required for auto-paste. "
                        "Text copied to clipboard — paste manually with ⌘V.\n"
                        "Grant access in System Settings → Privacy & Security → Accessibility."
                    )
                    logger.warning(msg)
                    try:
                        self.error_occurred.emit(msg)
                    except Exception:
                        pass
                    return
                logger.info("Paste succeeded")
            except FileNotFoundError as exc:
                msg = (
                    f"Missing helper program: {exc.filename}. "
                    "Install xclip+xdotool (X11) or wl-copy+wtype (Wayland)."
                )
                logger.error(msg)
                try:
                    self.error_occurred.emit(msg)
                except Exception:
                    pass
            except subprocess.SubprocessError as exc:
                msg = f"Paste failed: {exc}"
                logger.error(msg)
                try:
                    self.error_occurred.emit(msg)
                except Exception:
                    pass

        asyncio.ensure_future(_paste_async())

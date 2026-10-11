"""STT engine — records speech via a roomkit STT room and pastes transcribed text."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from PySide6.QtCore import QObject, Signal

from roomkit_ui.paste import (
    _activate_bundle,
    _copy_to_clipboard,
    _get_frontmost_bundle,
    _simulate_paste,
    paste_failure_message,
)
from roomkit_ui.settings import load_settings
from roomkit_ui.stt_sessions import DictationSessionMixin

# Re-exported for backward compatibility with any code that still does
# ``from roomkit_ui.stt_engine import _copy_to_clipboard``.  New callers
# should import from ``roomkit_ui.paste`` directly.
__all__ = [
    "DictationState",
    "STTEngine",
    "_activate_bundle",
    "_copy_to_clipboard",
    "_get_frontmost_bundle",
    "_simulate_paste",
]

logger = logging.getLogger(__name__)


class DictationState(Enum):
    """Where dictation is in its lifecycle.

    Opening a session takes about a second (the OpenAI websocket) and
    stopping one up to thirty (a batch flush).  A press that lands inside
    either transition is remembered and replayed once it settles — never
    run alongside it, which is how a second session used to leak and a
    stop used to tear down the session that replaced it.
    """

    IDLE = auto()
    STARTING = auto()
    RECORDING = auto()
    STOPPING = auto()


@dataclass
class _SessionObjects:
    """One dictation's roomkit objects, detached from the engine at stop."""

    kit: Any = None
    channel: Any = None
    session: Any = None
    provider: Any = None
    transport: Any = None
    local_provider: Any = None
    local_backend: Any = None
    local_session: Any = None
    local_flush_event: asyncio.Event | None = None
    batch_mode: bool = False

    @property
    def is_local(self) -> bool:
        return self.local_provider is not None

    @property
    def empty(self) -> bool:
        return not any((self.kit, self.channel, self.session, self.local_backend))


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
        self._state = DictationState.IDLE
        # A press received mid-transition, replayed once it settles.
        self._toggle_pending = False
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
        return self._state in (DictationState.STARTING, DictationState.RECORDING)

    def toggle_recording(self) -> None:
        logger.info(
            "toggle_recording: state=%s pending=%s",
            self._state.name,
            self._toggle_pending,
        )
        if self._state is DictationState.IDLE:
            asyncio.ensure_future(self._start_recording())
        elif self._state is DictationState.RECORDING:
            asyncio.ensure_future(self._stop_recording())
        else:
            # Mid-transition: a second press cancels the first.
            self._toggle_pending = not self._toggle_pending

    def _settle(self, state: DictationState) -> None:
        """End a transition, then replay a press that arrived during it."""
        self._state = state
        if self._toggle_pending:
            self._toggle_pending = False
            self.toggle_recording()

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
        if self._state is not DictationState.IDLE:
            logger.warning("_start_recording skipped: state=%s", self._state.name)
            return

        self._state = DictationState.STARTING
        self.recording_changed.emit(True)
        self._accumulated_text.clear()
        self._prev_app = _get_frontmost_bundle()
        logger.info("Saved frontmost app: %s", self._prev_app)

        started = False
        try:
            started = await self._open_session()
        finally:
            if started:
                self._settle(DictationState.RECORDING)
            else:
                # Nothing is left to stop: a press made while connecting
                # would only start a new attempt the user did not ask for.
                self._discard_session()
                self._toggle_pending = False
                self.recording_changed.emit(False)
                self._settle(DictationState.IDLE)

    async def _open_session(self) -> bool:
        """Bring up the configured provider. False after reporting why not."""
        if os.environ.get("STT_FAKE"):
            logger.info("STT fake mode — will paste test text on stop")
            return True

        settings = load_settings()
        stt_provider = settings.get("stt_provider", "openai")
        if stt_provider == "local":
            return await self._start_local_recording(settings)
        if stt_provider == "deepgram":
            return await self._start_deepgram_recording(settings)
        return await self._start_openai_recording(settings)

    def _fail_start(self, message: str) -> None:
        """Report why a session could not be opened.

        Only the message: ``_start_recording`` restores the idle state once
        the provider builder returns.
        """
        self.error_occurred.emit(message)

    async def _stop_recording(self) -> None:
        if self._state is not DictationState.RECORDING:
            return

        self._state = DictationState.STOPPING
        self.recording_changed.emit(False)
        logger.info("STT recording stopped")
        # This stop owns these objects from here on: whatever runs while it
        # waits for the last words, its teardown reaches them and only them.
        objects = self._take_session()
        try:
            await self._collect_final_text(objects)
            await self._deliver_text()
        finally:
            self._dispose(objects)
            self._settle(DictationState.IDLE)

    async def _collect_final_text(self, objects: _SessionObjects) -> None:
        """Wait for whatever the provider still owes for this dictation."""
        if os.environ.get("STT_FAKE"):
            self._accumulated_text.append("Hello, this is a test transcription.")
        elif objects.is_local:
            await self._stop_local_recording(objects)
        elif not self._accumulated_text:
            # Only commit if we don't already have text from VAD —
            # committing an empty buffer causes a harmless but noisy error.
            await self._commit_and_wait(objects)

    async def _deliver_text(self) -> None:
        """Emit the transcript, after handing focus back to where it goes."""
        text = " ".join(self._accumulated_text).strip()
        if not text:
            logger.info("No transcription captured")
            return
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

    async def _stop_local_recording(self, objects: _SessionObjects) -> None:
        """Stop the LocalAudioBackend and wait for final transcriptions."""
        backend, session = objects.local_backend, objects.local_session
        if not (backend and session):
            return
        await backend.stop_listening(session)

        if objects.batch_mode:
            # Batch mode: flush accumulated audio through offline STT
            try:
                result = await asyncio.wait_for(
                    objects.channel.flush_stt(session),
                    timeout=30.0,
                )
                if result and result.text and result.text.strip():
                    logger.info("Batch STT result: %d chars", len(result.text))
                    logger.debug("Batch STT text: %s", result.text)
                    self._accumulated_text.append(result.text.strip())
            except TimeoutError:
                logger.warning("Batch STT timed out")
        elif objects.local_flush_event is not None:
            # Streaming mode: wait for final transcription from hook
            objects.local_flush_event.clear()
            try:
                await asyncio.wait_for(objects.local_flush_event.wait(), timeout=3.0)
            except TimeoutError:
                logger.info("No final transcription received within timeout")

    async def _commit_and_wait(self, objects: _SessionObjects) -> None:
        """Send input_audio_buffer.commit and wait for the transcription."""
        if objects.provider is None or objects.session is None:
            return

        self._transcription_event = asyncio.Event()
        # If we already have text from earlier VAD cycles, pre-set the event
        # so we don't block unnecessarily.
        if self._accumulated_text:
            self._transcription_event.set()

        try:
            await objects.provider.send_event(
                objects.session, {"type": "input_audio_buffer.commit"}
            )
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

    # -- teardown --------------------------------------------------------------

    def _take_session(self) -> _SessionObjects:
        """Detach the current session's objects so a new one starts clean."""
        objects = _SessionObjects(
            kit=self._kit,
            channel=self._channel,
            session=self._session,
            provider=self._provider,
            transport=self._transport,
            local_provider=self._local_provider,
            local_backend=self._local_backend,
            local_session=self._local_session,
            local_flush_event=self._local_flush_event,
            batch_mode=self._batch_mode,
        )
        self._kit = self._channel = self._session = None
        self._provider = self._transport = None
        self._local_provider = self._local_backend = self._local_session = None
        self._local_flush_event = None
        self._batch_mode = False
        return objects

    def _dispose(self, objects: _SessionObjects) -> None:
        """Close *objects* in the background — cleanup is slow."""
        if not objects.empty:
            asyncio.ensure_future(self._close_session(objects))

    def _discard_session(self) -> None:
        """Tear down whatever a failed start managed to open."""
        self._dispose(self._take_session())

    async def _close_session(self, objects: _SessionObjects) -> None:
        """Clean up a detached session without touching ``self``."""
        try:
            if objects.is_local:
                await self._close_local_session(objects)
            elif objects.channel and objects.session:
                try:
                    await objects.channel.end_session(objects.session)
                except Exception:
                    pass
            if objects.kit:
                try:
                    await objects.kit.close()
                except Exception:
                    pass
        except Exception:
            logger.exception("Error during STT cleanup")

    @staticmethod
    async def _close_local_session(objects: _SessionObjects) -> None:
        channel, backend, session = objects.channel, objects.local_backend, objects.local_session
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
                    msg = paste_failure_message()
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
            except (OSError, subprocess.SubprocessError) as exc:
                # OSError: the Win32 clipboard refused the text.
                msg = f"Paste failed: {exc}"
                logger.error(msg)
                try:
                    self.error_occurred.emit(msg)
                except Exception:
                    pass

        asyncio.ensure_future(_paste_async())

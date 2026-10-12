"""STT engine — records speech via a roomkit STT room and pastes transcribed text."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from PySide6.QtCore import QObject, Signal

from roomkit_ui.dictation_stream import DictationStream
from roomkit_ui.paste import (
    PasteError,
    _activate_bundle,
    _get_frontmost_bundle,
    paste_into_focused,
)
from roomkit_ui.settings import load_settings
from roomkit_ui.stt_sessions import DictationSessionMixin, dictation_unavailable

__all__ = ["DictationState", "STTEngine"]

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
    local_stream: DictationStream | None = None
    batch_mode: bool = False

    @property
    def is_local(self) -> bool:
        return self.local_provider is not None

    @property
    def empty(self) -> bool:
        return not any(
            (self.kit, self.channel, self.session, self.local_backend, self.local_provider)
        )


class STTEngine(DictationSessionMixin, QObject):
    """Records speech via a roomkit STT room and pastes the result.

    Supports three providers:
    - **OpenAI**: ``RealtimeVoiceChannel`` with ``create_response=False``
    - **Local**: warmed Sherpa-Onnx, streaming or offline (``VoiceChannel.flush_stt``)
    - **Deepgram**: streaming, with explicit end of audio on Stop
    """

    recording_changed = Signal(bool)
    state_changed = Signal(object)
    busy_changed = Signal(bool)
    text_ready = Signal(str)
    draft_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = DictationState.IDLE
        self._task: asyncio.Task | None = None
        self._cleanup_tasks: set[asyncio.Task] = set()
        self._to_input = False
        self._discard = False
        self._start_blocked = ""
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
        # STT capture state (local/Deepgram, with a VoiceChannel for offline models)
        self._local_provider: Any = None
        self._local_backend: Any = None
        self._local_session: Any = None
        self._local_stream: DictationStream | None = None
        self._cached_local_provider: Any = None
        self._cached_local_key: tuple | None = None
        self._batch_mode: bool = False

    @property
    def state(self) -> DictationState:
        return self._state

    @property
    def busy(self) -> bool:
        return self._state is not DictationState.IDLE

    @property
    def to_input(self) -> bool:
        return self._to_input

    def set_start_blocked(self, reason: str) -> None:
        self._start_blocked = reason

    def start_input(self) -> bool:
        """Claim the shared microphone for a draft, without focus or clipboard changes."""
        if self.busy or self._start_blocked:
            return False
        self._begin(to_input=True)
        return True

    def _begin(self, *, to_input: bool = False) -> None:
        self._to_input = to_input
        self._discard = False
        self._accumulated_text = []  # Hooks from a previous session keep their own list.
        self._set_state(DictationState.STARTING)
        self._task = asyncio.ensure_future(self._start_recording())

    def _set_state(self, state: DictationState) -> None:
        was_busy = self.busy
        self._state = state
        try:
            self.state_changed.emit(state)
            if was_busy != self.busy:
                self.busy_changed.emit(self.busy)
        except RuntimeError:
            pass  # Qt may have destroyed the window during shutdown.

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
            if self._start_blocked:
                self.error_occurred.emit(self._start_blocked)
                return
            self._begin()
        elif self._state is DictationState.RECORDING:
            self._set_state(DictationState.STOPPING)
            self._task = asyncio.ensure_future(self._stop_recording())
        elif self._to_input and self._state is DictationState.STOPPING:
            return  # Finishing a draft must never queue a system-wide paste.
        else:
            # Mid-transition: a second press cancels the first.
            self._toggle_pending = not self._toggle_pending

    def _settle(self, state: DictationState) -> None:
        """End a transition, then replay a press that arrived during it."""
        self._set_state(state)
        if self._toggle_pending:
            self._toggle_pending = False
            self.toggle_recording()

    def cancel(self) -> None:
        """Discard this capture, including a result still arriving from the provider."""
        if not self.busy or self._discard:
            return
        self._discard = True
        self._toggle_pending = False
        if self._state is DictationState.RECORDING:
            self._set_state(DictationState.STOPPING)
            self._task = asyncio.ensure_future(self._stop_recording())
        elif self._task is not None:
            # Let the lifecycle enter its try/finally even on an immediate cancel.
            asyncio.get_running_loop().call_soon(self._task.cancel)

    async def shutdown(self) -> None:
        self.cancel()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        if self._cleanup_tasks:
            await asyncio.gather(*self._cleanup_tasks, return_exceptions=True)
        await self._close_cached_local_stt()

    async def _close_cached_local_stt(self) -> None:
        provider, self._cached_local_provider = self._cached_local_provider, None
        self._cached_local_key = None
        if provider is not None:
            await provider.close()

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
        self.recording_changed.emit(True)
        self._prev_app = None if self._to_input else _get_frontmost_bundle()
        logger.info("Saved frontmost app: %s", self._prev_app)

        started = False
        try:
            if not self._discard:
                started = await self._open_session()
        except Exception as exc:
            logger.exception("Could not start dictation")
            self._fail_start(str(exc))
        finally:
            if started and not self._discard:
                self._settle(DictationState.RECORDING)
            else:
                # Nothing is left to stop: a press made while connecting
                # would only start a new attempt the user did not ask for.
                self._discard_session()
                self._toggle_pending = False
                self.recording_changed.emit(False)
                try:
                    await self._wait_cleanup()
                finally:
                    self._settle(DictationState.IDLE)

    async def _open_session(self) -> bool:
        """Bring up the configured provider. False after reporting why not."""
        if os.environ.get("STT_FAKE"):
            logger.info("STT fake mode — will paste test text on stop")
            return True

        settings = load_settings()
        if reason := dictation_unavailable(settings):
            self._fail_start(reason)
            return False
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
        self.recording_changed.emit(False)
        logger.info("STT recording stopped")
        # This stop owns these objects from here on: whatever runs while it
        # waits for the last words, its teardown reaches them and only them.
        objects = self._take_session()
        collected = False
        try:
            if not self._discard:
                await self._collect_final_text(objects)
                collected = True
        except Exception as exc:
            logger.exception("Could not finish dictation")
            self._fail_start(str(exc))
        finally:
            # Keep the microphone claimed until it has actually been released.
            self._dispose(objects)
            try:
                await self._wait_cleanup()
                if collected:
                    await self._deliver_text()
            finally:
                self._settle(DictationState.IDLE)

    async def _collect_final_text(self, objects: _SessionObjects) -> None:
        """Wait for whatever the provider still owes for this dictation."""
        if os.environ.get("STT_FAKE"):
            self._accumulated_text.append("Hello, this is a test transcription.")
        elif objects.is_local:
            await self._stop_local_recording(objects)
        else:
            if self._to_input and objects.transport is not None and objects.session is not None:
                await objects.transport.stop_listening(objects.session)
            if not self._accumulated_text:
                # Composer sessions disable server VAD and commit once, on
                # Finish. Global dictation may already have a final from VAD.
                await self._commit_and_wait(objects)

    async def _deliver_text(self) -> None:
        """Emit the transcript, after handing focus back to where it goes."""
        text = " ".join(self._accumulated_text).strip()
        if not text:
            logger.info("No transcription captured")
            if self._to_input and not self._discard:
                self.error_occurred.emit("No speech detected. Try dictating again.")
            return
        if self._discard:
            return
        if self._to_input:
            self.draft_ready.emit(text)
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
        started = time.monotonic()
        await backend.stop_listening(session)
        # Capture delivers on the loop. Drain frames queued before the device
        # stopped before sending EOF, so the very last syllable is included.
        await asyncio.sleep(0)

        if objects.local_stream is not None:
            self._accumulated_text.extend(await objects.local_stream.finish())
            logger.info("Streaming STT finalized in %.0f ms", (time.monotonic() - started) * 1000)
        elif objects.batch_mode:
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
            local_stream=self._local_stream,
            batch_mode=self._batch_mode,
        )
        self._kit = self._channel = self._session = None
        self._provider = self._transport = None
        self._local_provider = self._local_backend = self._local_session = None
        self._local_stream = None
        self._batch_mode = False
        return objects

    def _dispose(self, objects: _SessionObjects) -> asyncio.Task | None:
        """Close *objects* in the background — cleanup is slow."""
        if not objects.empty:
            task = asyncio.ensure_future(self._close_session(objects))
            self._cleanup_tasks.add(task)
            task.add_done_callback(self._cleanup_tasks.discard)
            return task
        return None

    def _discard_session(self) -> None:
        """Tear down whatever a failed start managed to open."""
        self._dispose(self._take_session())

    async def _wait_cleanup(self) -> None:
        if not self._cleanup_tasks:
            return
        cleanup = asyncio.gather(*self._cleanup_tasks, return_exceptions=True)
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            # Cancelling a transcription must not cancel release of its device.
            await cleanup
            raise

    async def _close_session(self, objects: _SessionObjects) -> None:
        """Clean up a detached session, retaining only a reusable warmed model."""
        try:
            if objects.is_local:
                await self._close_local_session(objects)
                if objects.local_stream is not None:
                    await objects.local_stream.close()
                    if (
                        objects.local_stream.task.cancelled()
                        and objects.local_provider is self._cached_local_provider
                    ):
                        # Cancelling asyncio.to_thread cannot stop a native
                        # decoder. A new capture gets a fresh recognizer.
                        self._cached_local_provider = self._cached_local_key = None
            elif objects.channel and objects.session:
                try:
                    await objects.channel.end_session(objects.session)
                except Exception:
                    logger.debug("dictation teardown: end_session failed", exc_info=True)
            if objects.kit:
                try:
                    await objects.kit.close()
                except Exception:
                    logger.debug("dictation teardown: kit.close() failed", exc_info=True)
        except Exception:
            logger.exception("Error during STT cleanup")
        finally:
            # A cancelled start may own audio before a kit registered it.
            if objects.kit is None:
                backend = objects.local_backend or objects.transport
                if backend is not None:
                    try:
                        await backend.close()
                    except Exception:
                        logger.debug("dictation teardown: backend.close failed", exc_info=True)
                if (
                    objects.local_provider is not None
                    and objects.local_provider is not self._cached_local_provider
                ):
                    try:
                        await objects.local_provider.close()
                    except Exception:
                        logger.debug("dictation teardown: provider.close failed", exc_info=True)

    @staticmethod
    async def _close_local_session(objects: _SessionObjects) -> None:
        channel, backend, session = objects.channel, objects.local_backend, objects.local_session
        if channel and session:
            try:
                channel.unbind_session(session)
            except Exception:
                logger.debug("dictation teardown: unbind_session failed", exc_info=True)
        if backend and session:
            try:
                await backend.disconnect(session)
            except Exception:
                logger.debug("dictation teardown: backend.disconnect failed", exc_info=True)

    # -- paste -----------------------------------------------------------------

    def paste_text(self, text: str) -> None:
        """Paste *text* into the app that had focus; say so when it fails."""

        async def _paste_async() -> None:
            front = _get_frontmost_bundle()
            logger.info("Pasting text to %s: %d chars", front or "(self)", len(text))
            logger.debug("Paste text payload: %s", text)
            try:
                await paste_into_focused(text)
            except PasteError as exc:
                logger.warning("%s", exc)
                try:
                    self.error_occurred.emit(str(exc))
                except Exception:
                    pass
                return
            logger.info("Paste succeeded")

        asyncio.ensure_future(_paste_async())

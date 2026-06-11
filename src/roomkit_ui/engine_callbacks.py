"""Provider / transport callback mixin for the voice engine.

Every ``on_*`` method here is wired onto a realtime provider or a
``LocalAudioBackend`` pipeline and must tolerate being invoked after
the Qt object has been deleted — hence ``_safe_emit``, which guards
every ``.emit()`` call and logs failures at DEBUG.
"""

from __future__ import annotations

import collections
import logging
from typing import Any

from roomkit_ui.engine_audio import friendly_error
from roomkit_ui.engine_state import EngineState

logger = logging.getLogger(__name__)


class CallbackMixin:
    """Provider + transport event handlers for ``Engine``.

    The mixin doesn't own any state — every attribute referenced here
    (``_state``, ``_mic_muted``, ``_partial_buffers``, etc.) lives on
    the concrete ``Engine`` class.  The annotations below let mypy
    resolve those attribute types inside mixin methods.
    """

    _state: EngineState
    _mic_muted: bool
    _current_speaker_id: str
    _primary_speaker_mode: bool
    _primary_speaker_name: str
    _partial_buffers: dict[str, str]
    _transport: Any
    _spk_rms_queue: collections.deque[float]

    def _safe_emit(self, signal: Any, *args: Any) -> None:
        """Emit *signal*, tolerating deletion of the underlying C++ object."""
        try:
            signal.emit(*args)
        except Exception:
            logger.debug("signal emit failed (Qt object deleted?)", exc_info=True)

    def _register_callbacks(self, provider: Any, transport: Any) -> None:
        # NOTE: on_transcription is NOT registered here — the channel fires
        # ON_TRANSCRIPTION hooks which register_realtime_hooks() handles.
        # Registering both would cause double transcription in the UI.
        provider.on_speech_start(self._on_speech_start)
        provider.on_speech_end(self._on_speech_end)
        provider.on_response_start(self._on_response_start)
        provider.on_response_end(self._on_response_end)
        provider.on_error(self._on_provider_error)

    def _on_transcription(self, _s: Any, text: str, role: str, is_final: bool) -> None:
        """Realtime transcription callback.

        Gemini/OpenAI send incremental fragments for partials.
        Accumulate them so the signal always carries the full text.
        """
        try:
            speaker = self._current_speaker_id if role == "user" else ""  # type: ignore[attr-defined]

            # Primary speaker mode: block non-primary user transcriptions
            if (
                role == "user"
                and self._primary_speaker_mode  # type: ignore[attr-defined]
                and self._primary_speaker_name  # type: ignore[attr-defined]
                and speaker != self._primary_speaker_name  # type: ignore[attr-defined]
            ):
                if is_final:
                    self._partial_buffers.pop(role, None)  # type: ignore[attr-defined]
                    label = speaker if speaker and speaker != "unknown" else "Unknown"
                    self.transcription.emit(str(text), "other", True, label)  # type: ignore[attr-defined]
                return

            if is_final:
                self._partial_buffers.pop(role, None)  # type: ignore[attr-defined]
                self.transcription.emit(str(text), str(role), True, speaker)  # type: ignore[attr-defined]
            else:
                buf = self._partial_buffers.get(role, "")  # type: ignore[attr-defined]
                buf += text
                self._partial_buffers[role] = buf  # type: ignore[attr-defined]
                self.transcription.emit(buf, str(role), False, speaker)  # type: ignore[attr-defined]
        except Exception:
            logger.debug("transcription callback failed", exc_info=True)

    def _drain_speaker_level(self) -> None:
        """Pop one RMS value per timer tick → matches real playback cadence."""
        if self._spk_rms_queue:  # type: ignore[attr-defined]
            self.speaker_audio_level.emit(self._spk_rms_queue.popleft())  # type: ignore[attr-defined]

    def _on_speech_start(self, _s: Any) -> None:
        self._safe_emit(self.user_speaking, True)  # type: ignore[attr-defined]

    def _on_speech_end(self, _s: Any) -> None:
        self._safe_emit(self.user_speaking, False)  # type: ignore[attr-defined]

    def _on_response_start(self, _s: Any) -> None:
        self._safe_emit(self.ai_speaking, True)  # type: ignore[attr-defined]

    def _on_response_end(self, _s: Any) -> None:
        self._safe_emit(self.ai_speaking, False)  # type: ignore[attr-defined]

    def _on_provider_error(self, _s: Any, code: str, message: str) -> None:
        # Suppress errors during shutdown — WebSocket close races are expected
        if self._state not in (EngineState.ACTIVE, EngineState.CONNECTING):  # type: ignore[attr-defined]
            logger.debug("Suppressed provider error (%s): %s: %s", self._state, code, message)  # type: ignore[attr-defined]
            return
        friendly = friendly_error(code, message)
        logger.warning("Provider error: %s: %s → %s", code, message, friendly)
        self._safe_emit(self.error_occurred, friendly)  # type: ignore[attr-defined]

    def _on_transport_speaker_change(self, session: Any, result: Any) -> None:
        """Handle speaker change events directly from the transport pipeline."""
        speaker_id = result.speaker_id
        confidence = result.confidence
        self._current_speaker_id = speaker_id  # type: ignore[attr-defined]
        self._safe_emit(self.speaker_identified, speaker_id, confidence)  # type: ignore[attr-defined]

        # Primary speaker gating: gate audio when a *different* enrolled
        # speaker is positively identified.  Unknown / empty speakers get
        # benefit of the doubt (diarization hasn't decided yet).
        if self._primary_speaker_mode and self._primary_speaker_name:  # type: ignore[attr-defined]
            gate = (
                bool(speaker_id)
                and speaker_id != "unknown"
                and speaker_id != self._primary_speaker_name  # type: ignore[attr-defined]
            )
            if self._transport is not None:  # type: ignore[attr-defined]
                self._transport.set_input_gated(session, gate)  # type: ignore[attr-defined]

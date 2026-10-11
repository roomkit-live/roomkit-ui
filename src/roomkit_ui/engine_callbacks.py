"""Realtime provider callback mixin for the voice engine.

Every ``_on_*`` method here is wired onto a realtime provider and must
tolerate being invoked after the Qt object has been deleted — hence
``_safe_emit``, which guards every ``.emit()`` call and logs failures at
DEBUG.
"""

from __future__ import annotations

import collections
import logging
from collections.abc import Callable
from typing import Any

from roomkit_ui.engine_audio import friendly_error
from roomkit_ui.engine_state import EngineState

logger = logging.getLogger(__name__)


class CallbackMixin:
    """Realtime provider event handlers for ``Engine``.

    The mixin doesn't own any state — every attribute referenced here
    (``_state``, ``_spk_rms_queue``) lives on the concrete ``Engine``
    class.  The annotations below let mypy resolve those attribute types
    inside mixin methods.
    """

    _state: EngineState
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
        provider.on_usage(self._realtime_usage_handler())

    def _realtime_usage_handler(self) -> Callable[[Any, dict], None]:
        """A provider's ``on_usage`` callback: each report joins the session totals.

        roomkit relays the provider's reports (RFC §12.4.2): one response's
        ``input_tokens``/``output_tokens``, beside a breakdown of the
        provider's own.  They go through the voice channel's accounting, so
        the info bar shows realtime tokens too — without a cost: realtime
        catalogs carry no price (audio tokens are priced apart).

        GPT-Live bills session seconds and puts its hosted backend's tokens
        under ``backend``.  That record stays in the session's usage map
        until the turn ends, so the next report (the seconds) repeats it:
        it is counted when it changes, once.
        """
        last_backend: dict | None = None

        def on_usage(_session: Any, usage: dict) -> None:
            nonlocal last_backend
            if self._state not in (EngineState.ACTIVE, EngineState.CONNECTING):
                return
            tokens = _token_counts(usage)
            backend = usage.get("backend")
            if isinstance(backend, dict) and backend != last_backend:
                last_backend = backend
                backend_tokens = _token_counts(backend)
                tokens = {key: tokens[key] + backend_tokens[key] for key in tokens}
            if any(tokens.values()):
                self._accumulate_usage(tokens)  # type: ignore[attr-defined]

        return on_usage

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


def _token_counts(usage: dict) -> dict[str, int]:
    """The two totals roomkit fixes, as ints; absent or garbage counts as zero."""
    from roomkit_ui.engine_vc import _usage_int

    return {key: _usage_int(usage, key) for key in ("input_tokens", "output_tokens")}
